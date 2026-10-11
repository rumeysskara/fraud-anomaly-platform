"""Step 6: context-aware adjustment of anomaly_score_norm + before/after FP report and ablation.

Usage: SAMPLE_N=50000 python scripts/run_context.py   (omit SAMPLE_N for the full data)
Reads data/processed/features[_sample].parquet, merged[_sample].parquet, reports/scores[/sample]/
raw_score.parquet + layer_scores.parquet and artifacts/detectors[/sample]/scoring_meta.joblib.
Learns the context params on the FIT rows only and writes them to the directory given by
configs/context.yaml paths.params_dir.
The label is read ONLY in evaluate_holdout(), via the loader and src.evaluation.metrics; the
adjustment itself never sees it. Use --no-eval to skip evaluation.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.context.config import load_context_config  # noqa: E402
from src.context.engine import (  # noqa: E402
    ADJUSTED_SCORE,
    APPLIED,
    GUARD_ACTIVE,
    ContextAdjustEngine,
)
from src.context.factory import params_directory  # noqa: E402
from src.context.inputs import RAW_SOURCE_COLUMNS, build_batch_inputs  # noqa: E402
from src.context.params import ContextParams  # noqa: E402
from src.context.report import (  # noqa: E402
    alarm_composition,
    rule_coverage,
    run_ablation,
    tie_break_order,
)
from src.core.config import (  # noqa: E402
    ARTIFACTS_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    get_sample_n,
    load_settings,
    load_yaml,
    set_seed,
)
from src.data.loader import split_by_time  # noqa: E402
from src.scoring.service import META_FILE, NORM_COL, RAW_COL  # noqa: E402

log = logging.getLogger("run_context")


def load_inputs(
    sfx: str, sub: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """features, raw fields, layer scores and Step 5 scores (all indexed by TransactionID)."""
    feats = pd.read_parquet(PROCESSED_DIR / f"features{sfx}.parquet")
    raw = pd.read_parquet(PROCESSED_DIR / f"merged{sfx}.parquet", columns=RAW_SOURCE_COLUMNS)
    score_dir = REPORTS_DIR / "scores" / sub
    layers = pd.read_parquet(score_dir / "layer_scores.parquet")
    scores = pd.read_parquet(score_dir / "raw_score.parquet")
    return feats, raw.loc[feats.index], layers, scores


def evaluate_holdout(
    result: pd.DataFrame,
    inputs: pd.DataFrame,
    holdout: pd.Index,
    engine: ContextAdjustEngine,
    out: Path,
) -> None:
    """Before/after metrics and the ablation table on holdout; the only place y is read."""
    from src.data.loader import load_data
    from src.evaluation.metrics import evaluate

    budgets = load_settings()["evaluation"]["alarm_budgets"]
    _, y = load_data()
    # rows ordered by the unnormalized Step 5 score: equal adjusted scores (1.0 saturation) are
    # then ranked by it in the stable top-k of src/evaluation (see report.tie_break_order)
    y_hold = y.loc[tie_break_order(result.loc[holdout, RAW_COL])]
    log.info("holdout rows %s, positives %s", len(y_hold), int(y_hold.sum()))

    def ev(score: pd.Series) -> dict[str, float]:
        return evaluate(y_hold, score.loc[y_hold.index], budgets)

    rows = []
    for name, col in (("before", "raw_score"), ("after", ADJUSTED_SCORE)):
        m = ev(result[col])
        for b in budgets:
            alarms = math.ceil(b * len(y_hold))
            fp = int(m[f"fp@{b}"])
            rows.append(
                {
                    "budget": b,
                    "score": name,
                    "alarms": alarms,
                    "tp": alarms - fp,
                    "fp": fp,
                    "precision": m[f"precision@{b}"],
                    "recall": m[f"recall@{b}"],
                    "fp_share_of_alarms": fp / alarms,
                    "pr_auc": m["pr_auc"],
                    "roc_auc": m["roc_auc"],
                    "rows_at_score_1": int((result.loc[holdout, col] >= 1.0).sum()),
                }
            )
    impact = pd.DataFrame(rows)
    impact.to_parquet(out / "fp_impact.parquet", index=False)
    impact.to_csv(out / "fp_impact.csv", index=False)

    hold_inputs = inputs.loc[holdout]
    raw_hold = result.loc[holdout, "raw_score"]
    table = run_ablation(engine, hold_inputs, raw_hold, ev)
    table.to_csv(out / "ablation.csv", index=False)
    pd.DataFrame([{"n": len(y_hold), "positives": int(y_hold.sum())}]).to_csv(
        out / "holdout_base.csv", index=False
    )


def main() -> int:
    """Run Step 6."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-eval", action="store_true", help="skip holdout evaluation")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    sample_n = get_sample_n()
    sfx, sub = ("_sample", "sample") if sample_n else ("", "")
    t0 = time.time()

    cfg = load_context_config()
    feats, raw, layers, scores = load_inputs(sfx, sub)
    fit_raw, hold_raw = split_by_time(raw[["TransactionDT"]])
    fit_idx, hold_idx = fit_raw.index, hold_raw.index
    log.info("rows %s (fit %s, holdout %s)", len(feats), len(fit_idx), len(hold_idx))

    params = ContextParams.fit(raw.loc[fit_idx], cfg)
    params_path = params.save(params_directory(cfg, bool(sample_n)))
    log.info("learned params %s -> %s", params.values, params_path)
    step3_addr2 = load_yaml("entity.yaml")["learned"]["dominant_addr2"]
    if params.values.get("dominant_addr2") != step3_addr2:
        log.warning("dominant addr2 differs from Step 3 (%s)", step3_addr2)

    meta = joblib.load(ARTIFACTS_DIR / "detectors" / sub / META_FILE)
    engine = ContextAdjustEngine(cfg, params, meta["weights"], meta["aggregate_normalizer"])
    inputs = build_batch_inputs(feats, raw, layers, meta["weights"])
    del feats

    check = engine.normalized_aggregate(inputs, engine.weights)
    diff = float(abs(check - scores[NORM_COL].loc[inputs.index].to_numpy()).max())
    log.info("re-aggregated vs Step 5 anomaly_score_norm, max abs diff %.2e", diff)

    result = engine.adjust_batch(inputs, scores[NORM_COL])
    result.insert(0, RAW_COL, scores.loc[result.index, RAW_COL].astype("float64"))

    out = REPORTS_DIR / "context" / sub
    out.mkdir(parents=True, exist_ok=True)
    adjusted_path = (out if sample_n else REPORTS_DIR / "scores") / "adjusted_score.parquet"
    result.to_parquet(adjusted_path)
    log.info("wrote %s", adjusted_path)

    parts = {"fit": fit_idx, "holdout": hold_idx}
    rule_coverage(result, cfg, parts).to_csv(out / "rule_coverage.csv", index=False)
    budgets = load_settings()["evaluation"]["alarm_budgets"]
    long_history = int(load_yaml("context.yaml")["reporting"]["long_history_min"])
    comp = alarm_composition(
        result.loc[hold_idx, "raw_score"],
        result.loc[hold_idx, ADJUSTED_SCORE],
        inputs.loc[hold_idx],
        result.loc[hold_idx, GUARD_ACTIVE],
        budgets,
        long_history,
        result.loc[hold_idx, RAW_COL],
    )
    comp.to_csv(out / "alarm_composition.csv", index=False)
    cols = ["raw_score", ADJUSTED_SCORE, "adjustment_total", "adjustment_unbounded"]
    result.loc[hold_idx, cols].describe().T.to_csv(out / "score_summary.csv")
    example = result.loc[hold_idx].sort_values(ADJUSTED_SCORE, ascending=False).head(5)
    example[["raw_score", ADJUSTED_SCORE, "adjustment_total", APPLIED]].to_json(
        out / "examples.json", orient="index", indent=2
    )

    if not args.no_eval:
        evaluate_holdout(result, inputs, hold_idx, engine, out)
    log.info("done in %.0fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
