"""Steps 4-5: fit the four anomaly layers, normalize, aggregate, save, evaluate on holdout.

Usage: SAMPLE_N=50000 python scripts/run_scoring.py   (omit SAMPLE_N for the full data)
Reads data/processed/features[_sample].parquet and merged[_sample].parquet (card1, addr1,
DeviceInfo, TransactionDT only). Writes artifacts/detectors[/sample] and reports/scores[/sample].
The label is read ONLY in evaluate_holdout(), via the loader and src.evaluation.metrics; the
scoring path (fit, weights, normalization) never sees it. Use --no-eval to skip evaluation.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import (  # noqa: E402
    ARTIFACTS_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    get_sample_n,
    load_settings,
    set_seed,
)
from src.data.loader import split_by_time  # noqa: E402
from src.detection.aux import AUX_SOURCE_COLUMNS, build_aux  # noqa: E402
from src.detection.config import load_anomaly_config, load_weights  # noqa: E402
from src.detection.factory import LAYERS, build_detector  # noqa: E402
from src.scoring.service import NORM_COL, RAW_COL, ScoringService  # noqa: E402

log = logging.getLogger("run_scoring")


def load_inputs(sfx: str, sample: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.Index, pd.Index]:
    """Features + aux columns, the catalog, and the fit / holdout index (time split)."""
    feats = pd.read_parquet(PROCESSED_DIR / f"features{sfx}.parquet")
    cols = ["TransactionDT", *AUX_SOURCE_COLUMNS]
    raw = pd.read_parquet(PROCESSED_DIR / f"merged{sfx}.parquet", columns=cols)
    raw = raw.loc[feats.index]
    fit_raw, hold_raw = split_by_time(raw[["TransactionDT"]])
    df = feats.join(build_aux(raw))
    cat_dir = REPORTS_DIR / "features" / ("sample" if sample else "")
    catalog = pd.read_parquet(cat_dir / "feature_catalog.parquet")
    return df, catalog, fit_raw.index, hold_raw.index


def evaluate_holdout(
    scores: pd.DataFrame, holdout: pd.Index, fit_scores: pd.DataFrame, extra: pd.Series, out: Path
) -> None:
    """Holdout metrics (layers, combined) and the ablation table; the only place y is read."""
    from src.data.loader import load_data
    from src.evaluation.metrics import evaluate
    from src.scoring.ablation import ablation_table

    settings = load_settings()
    budgets = settings["evaluation"]["alarm_budgets"]
    _, y = load_data()
    y_hold = y.loc[holdout]
    log.info("holdout rows %s, positives %s", len(y_hold), int(y_hold.sum()))

    def ev(score: pd.Series) -> dict[str, float]:
        return evaluate(y_hold, score.loc[holdout], budgets)

    layer_cols = {n: scores[f"{n}_score"] for n in LAYERS}
    rows = [{"scope": n, **ev(s)} for n, s in layer_cols.items()]
    rows.append({"scope": "combined (raw_anomaly_score)", **ev(scores[RAW_COL])})
    rows.append({"scope": "combined (anomaly_score_norm)", **ev(scores[NORM_COL])})
    pd.DataFrame(rows).to_csv(out / "holdout_metrics.csv", index=False)

    hold = {n: s.loc[holdout] for n, s in layer_cols.items()}
    fit = {n: fit_scores[f"{n}_score"] for n in LAYERS}
    table = ablation_table(hold, fit, load_weights(), ev, alt_multivariate=extra.loc[holdout])
    table.to_csv(out / "ablation.csv", index=False)
    pd.Series(table.attrs["corr_weights"], name="weight").to_csv(out / "corr_weights.csv")
    base = pd.DataFrame({"n": [len(y_hold)], "positives": [int(y_hold.sum())]})
    base.to_csv(out / "holdout_base.csv", index=False)


def main() -> int:
    """Run Steps 4-5."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-eval", action="store_true", help="skip holdout evaluation")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    sample_n = get_sample_n()
    sfx = "_sample" if sample_n else ""
    t0 = time.time()

    df, catalog, fit_idx, hold_idx = load_inputs(sfx, bool(sample_n))
    log.info("rows %s (fit %s, holdout %s)", len(df), len(fit_idx), len(hold_idx))
    cfg, weights = load_anomaly_config(), load_weights()

    service = ScoringService.fit(df.loc[fit_idx], cfg, catalog, weights)
    service.build_hour_store(df)
    art_dir = ARTIFACTS_DIR / "detectors" / ("sample" if sample_n else "")
    service.save(art_dir)
    log.info("fitted + saved to %s (%.0fs)", art_dir, time.time() - t0)

    scores = service.score_batch(df)
    out = REPORTS_DIR / "scores" / ("sample" if sample_n else "")
    out.mkdir(parents=True, exist_ok=True)
    layer_cols = [f"{n}_score" for n in LAYERS]
    raw_cols = [f"raw_{n}" for n in LAYERS]
    scores[layer_cols + raw_cols].to_parquet(out / "layer_scores.parquet")
    contrib = [c for c in scores.columns if c.startswith("contrib_")]
    scores[[RAW_COL, NORM_COL, *contrib]].to_parquet(out / "raw_score.parquet")
    scores[layer_cols].loc[fit_idx].corr(method="spearman").to_csv(out / "layer_corr_fit.csv")
    scores[layer_cols].loc[hold_idx].corr(method="spearman").to_csv(out / "layer_corr_holdout.csv")
    scores[layer_cols + [RAW_COL, NORM_COL]].describe().T.to_csv(out / "score_summary.csv")
    for name in LAYERS:
        det = service.detectors[name]
        if name == "multivariate":
            cols = pd.Series(det.pre.output_columns, name="input")
            cols.to_csv(out / "mv_input.csv", index=False)
            logs = pd.Series(det.pre.log_cols, name="signed_log")
            logs.to_csv(out / "mv_logcols.csv", index=False)

    full_det = build_detector("multivariate", cfg, catalog, list(df.columns), full=True)
    full_det.fit(df.loc[fit_idx])
    extra = full_det.score(df)
    log.info("IF-full inputs: %s", len(full_det.pre.output_columns))

    if not args.no_eval:
        evaluate_holdout(scores, hold_idx, scores.loc[fit_idx], extra, out)
    log.info("done in %.0fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
