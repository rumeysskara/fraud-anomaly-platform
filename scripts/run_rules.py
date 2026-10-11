"""Step 7: rule engine on top of the Step 6 adjusted score + label-free and holdout reports.

Usage: SAMPLE_N=50000 python scripts/run_rules.py   (omit SAMPLE_N for the full data)
Reads data/processed/features[_sample].parquet, merged[_sample].parquet and the Step 6 output
(reports/scores/adjusted_score.parquet; sample: reports/context/sample/adjusted_score.parquet).
Thresholds are learned on the FIT rows only. Full data: written to the `learned:` block of
configs/rules.yaml (the API reads them from there); SAMPLE_N runs: reports/rules/sample/.
The label is read ONLY in evaluate_holdout(), via the loader and src.evaluation.metrics; rules,
thresholds and boosts never see it. Use --no-eval to skip evaluation.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.context.report import tie_break_order  # noqa: E402
from src.core.config import (  # noqa: E402
    CONFIG_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    get_sample_n,
    load_settings,
    load_yaml,
    set_seed,
)
from src.data.loader import split_by_time  # noqa: E402
from src.rules.derive import build_batch_inputs, merged_columns  # noqa: E402
from src.rules.engine import (  # noqa: E402
    ADJUSTED,
    ADJUSTED_UNCLIPPED,
    ANOMALY,
    FINAL_UNCLIPPED,
    HIT_PREFIX,
    RuleEngine,
)
from src.rules.params import (  # noqa: E402
    external_params,
    fit_params,
    save_params_json,
    write_learned_block,
)
from src.rules.report import (  # noqa: E402
    boost_summary,
    conflict_summary,
    decision_distribution,
    pick_conflict_examples,
    rule_coverage,
)
from src.rules.repository import RuleRepository  # noqa: E402

log = logging.getLogger("run_rules")
RAW_TIEBREAK = "raw_anomaly_score"


def load_inputs(sfx: str, sample: bool, repo: RuleRepository) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rule inputs and Step 5/6 scores, both indexed by TransactionID."""
    inp = repo.settings.inputs
    feats = pd.read_parquet(PROCESSED_DIR / f"features{sfx}.parquet", columns=inp["features"])
    merged = pd.read_parquet(
        PROCESSED_DIR / f"merged{sfx}.parquet", columns=merged_columns(inp["raw"])
    )
    path = REPORTS_DIR / ("context/sample" if sample else "scores") / "adjusted_score.parquet"
    adj = pd.read_parquet(path)
    scores = pd.DataFrame(
        {
            ANOMALY: adj["raw_score"],
            ADJUSTED: adj["adjusted_score"],
            ADJUSTED_UNCLIPPED: adj["adjusted_score_unclipped"],
            RAW_TIEBREAK: adj[RAW_TIEBREAK],
        }
    ).loc[feats.index]
    inputs = build_batch_inputs(feats, merged, inp["features"], inp["raw"])
    inputs["TransactionDT"] = merged.loc[feats.index, "TransactionDT"]
    return inputs, scores


def learn_params(
    repo: RuleRepository, fit_frame: pd.DataFrame, sample: bool, out: Path
) -> dict[str, object]:
    """Fit thresholds on fit rows; save them (config for full data, JSON always)."""
    learned = fit_params(fit_frame, repo.settings)
    external = external_params(repo.settings, sample)
    save_params_json(out, learned, external)
    if not sample:
        write_learned_block(repo.config_path, learned)
        repo.reload()
    step3 = load_yaml("entity.yaml")["learned"]["small_amt_threshold"]
    # float32 amounts: compare with a cent-level tolerance
    if not sample and abs(learned["amount_small"] - step3) > 1e-3:
        log.warning("amount_small %s differs from Step 3 small_amt_threshold %s", learned, step3)
    log.info("learned %s, external %s", learned, external)
    return {**learned, **external}


def online_check(engine: RuleEngine, inputs: pd.DataFrame, result: pd.DataFrame, ids: list) -> int:
    """Re-evaluate rows through the single-record path; return the number of mismatches."""
    bad = 0
    for tid in ids:
        record = record_of(inputs, result, tid)
        one = engine.evaluate(record, float(result.at[tid, ADJUSTED_UNCLIPPED]))
        same = (
            one.final_decision == result.at[tid, "final_decision"]
            and one.triggered_rules == list(result.at[tid, "triggered_rules"])
            and math.isclose(one.final_score_unclipped, result.at[tid, FINAL_UNCLIPPED])
        )
        bad += not same
    return bad


def record_of(inputs: pd.DataFrame, result: pd.DataFrame, tid: int) -> dict:
    """One input row as an API-like record (with the display scores)."""
    record = inputs.loc[tid].to_dict()
    record[ANOMALY] = float(result.at[tid, ANOMALY])
    record[ADJUSTED] = float(result.at[tid, ADJUSTED])
    return record


def evaluate_holdout(result: pd.DataFrame, engine: RuleEngine, hold: pd.Index, out: Path) -> None:
    """Rule precision/lift, decision metrics, budget comparison and ablation; the only place y
    is read (loader + src.evaluation.metrics). Nothing here changes a rule or threshold."""
    from src.data.loader import load_data
    from src.evaluation.metrics import evaluate

    budgets = load_settings()["evaluation"]["alarm_budgets"]
    _, y = load_data()
    # stable top-k: equal scores are ranked by the unnormalized Step 5 score (as in Step 6)
    y_hold = y.loc[tie_break_order(result.loc[hold, RAW_TIEBREAK])]
    base = float(y_hold.mean())
    res = result.loc[y_hold.index]
    log.info("holdout rows %s, positives %s", len(y_hold), int(y_hold.sum()))

    rows = []
    for col in [c for c in res.columns if c.startswith(HIT_PREFIX)]:
        rid = col[len(HIT_PREFIX) :]
        hit = res[col] == 1
        applied = res["applied_rules"].map(lambda x, r=rid: r in x)
        prec = float(y_hold[hit].mean()) if hit.any() else float("nan")
        rows.append(
            {
                "id": rid,
                "hits": int(hit.sum()),
                "coverage": float(hit.mean()),
                "tp": int(y_hold[hit].sum()),
                "precision": prec,
                "lift": prec / base if hit.any() else float("nan"),
                "applied": int(applied.sum()),
                "precision_applied": (
                    float(y_hold[applied].mean()) if applied.any() else float("nan")
                ),
            }
        )
    pd.DataFrame(rows).to_csv(out / "rule_metrics.csv", index=False)

    dec = res.groupby("final_decision").size().rename("rows").to_frame()
    dec["tp"] = y_hold.groupby(res["final_decision"]).sum()
    dec["fp"] = dec["rows"] - dec["tp"]
    dec["precision"] = dec["tp"] / dec["rows"]
    dec["lift"] = dec["precision"] / base
    dec.reset_index().to_csv(out / "decision_metrics.csv", index=False)

    def ev(score: pd.Series) -> dict[str, float]:
        return evaluate(y_hold, score.loc[y_hold.index], budgets)

    comp = []
    for name, col in (
        ("step5 (anomaly_score_norm)", ANOMALY),
        ("step6 (adjusted_score_unclipped)", ADJUSTED_UNCLIPPED),
        ("step7 (final_score_unclipped)", FINAL_UNCLIPPED),
    ):
        m = ev(result[col])
        for b in budgets:
            k = math.ceil(b * len(y_hold))
            comp.append(
                {
                    "budget": b,
                    "score": name,
                    "alarms": k,
                    "tp": k - int(m[f"fp@{b}"]),
                    "fp": int(m[f"fp@{b}"]),
                    "precision": m[f"precision@{b}"],
                    "recall": m[f"recall@{b}"],
                    "pr_auc": m["pr_auc"],
                    "roc_auc": m["roc_auc"],
                }
            )
    table = pd.DataFrame(comp).sort_values("budget", kind="stable")
    table.to_csv(out / "budget_comparison.csv", index=False)
    log.info("budget comparison\n%s", table.to_string(index=False))

    # leave-one-rule-out on the final score (same hits, one rule removed before resolution)
    rules = engine.active_rules()
    hit_cols = [f"{HIT_PREFIX}{r.id}" for r in rules]
    hits = res[hit_cols].astype(bool).set_axis([r.id for r in rules], axis=1)
    abl = []
    for rule in [None, *rules]:
        keep = [r for r in rules if rule is None or r.id != rule.id]
        decided = engine.decide(hits[[r.id for r in keep]], keep, res[ADJUSTED_UNCLIPPED])
        m = ev(decided[FINAL_UNCLIPPED])
        row = {"variant": "all rules" if rule is None else f"without {rule.id}"}
        row["pr_auc"] = m["pr_auc"]
        for b in budgets:
            row[f"precision@{b}"] = m[f"precision@{b}"]
            row[f"fp@{b}"] = int(m[f"fp@{b}"])
        row["review_or_block_rows"] = int(decided["final_decision"].isin(["review", "block"]).sum())
        abl.append(row)
    pd.DataFrame(abl).to_csv(out / "rule_ablation.csv", index=False)
    pd.DataFrame([{"n": len(y_hold), "positives": int(y_hold.sum()), "base_rate": base}]).to_csv(
        out / "holdout_base.csv", index=False
    )


def main() -> int:
    """Run Step 7."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-eval", action="store_true", help="skip holdout evaluation")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    sample = bool(get_sample_n())
    sfx = "_sample" if sample else ""
    out = REPORTS_DIR / "rules" / ("sample" if sample else "")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    repo = RuleRepository(CONFIG_DIR / "rules.yaml")
    inputs, scores = load_inputs(sfx, sample, repo)
    fit_part, hold_part = split_by_time(inputs[["TransactionDT"]])
    fit_idx, hold_idx = fit_part.index, hold_part.index
    inputs = inputs.drop(columns="TransactionDT")
    log.info("rows %s (fit %s, holdout %s)", len(inputs), len(fit_idx), len(hold_idx))

    fit_frame = inputs.loc[fit_idx].join(scores.loc[fit_idx])
    params = learn_params(repo, fit_frame, sample, out)
    del fit_frame
    engine = RuleEngine(repo, params)
    rules = engine.active_rules()
    log.info("active rules: %s", [r.id for r in rules])

    result = engine.evaluate_batch(inputs, scores)
    result.insert(0, RAW_TIEBREAK, scores[RAW_TIEBREAK])
    result.to_parquet(out / "rule_hits.parquet")
    log.info("wrote %s", out / "rule_hits.parquet")

    parts = {"fit": fit_idx, "holdout": hold_idx}
    rule_coverage(result, rules, parts).to_csv(out / "rule_coverage.csv", index=False)
    decision_distribution(result, parts).to_csv(out / "decision_distribution.csv", index=False)
    pd.concat(
        [conflict_summary(result, idx).assign(part=p) for p, idx in parts.items()],
        ignore_index=True,
    ).to_csv(out / "conflicts.csv", index=False)
    pd.concat(
        [boost_summary(result, idx).assign(part=p) for p, idx in parts.items()], ignore_index=True
    ).to_csv(out / "score_effect.csv", index=False)

    allow_ids = {r.id for r in rules if r.action.decision == "allow"}
    examples = {}
    # conflicts are rare (high-amount and small-amount rules exclude each other), so examples are
    # picked label-free from all rows; `part` tells where the row comes from
    for tid in pick_conflict_examples(result, result.index, allow_ids, n=4):
        one = engine.evaluate(
            record_of(inputs, result, tid), float(result.at[tid, ADJUSTED_UNCLIPPED])
        )
        part = "holdout" if tid in hold_idx else "fit"
        examples[str(tid)] = {"transaction_id": tid, "part": part, **one.explain_dict()}
    (out / "conflict_examples.json").write_text(json.dumps(examples, indent=2, ensure_ascii=False))
    log.info("conflict examples: %s", list(examples))

    rng = np.random.default_rng(load_settings()["seed"])
    triggered = result.index[result["triggered_rules"].map(len) > 0]
    sample_ids = list(rng.choice(result.index, size=min(100, len(result)), replace=False))
    sample_ids += list(rng.choice(triggered, size=min(100, len(triggered)), replace=False))
    mismatches = online_check(engine, inputs, result, sample_ids)
    log.info("batch vs single-record check: %s rows, %s mismatches", len(sample_ids), mismatches)
    if mismatches:
        log.error("batch and single-record paths disagree")
        return 1

    if not args.no_eval:
        evaluate_holdout(result, engine, hold_idx, out)
    log.info("done in %.0fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
