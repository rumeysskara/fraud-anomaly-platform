"""Step 7: rule engine on top of the Step 6 adjusted score + label-free and holdout reports.

Usage: SAMPLE_N=50000 python scripts/run_rules.py   (omit SAMPLE_N for the full data)
Reads data/processed/features[_sample].parquet, merged[_sample].parquet and the Step 6 output
(reports/scores/adjusted_score.parquet; sample: reports/context/sample/adjusted_score.parquet).
Thresholds are learned on the FIT rows only. Full data: written to the `learned:` block of
configs/rules.yaml (the API reads them from there); SAMPLE_N runs: reports/rules/sample/.
Labelled metrics are computed only in src/evaluation (rule_metrics, metrics); this script passes
label-free masks and scores to them in evaluate(). Use --no-eval to skip evaluation.
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
from src.rules.cooldown import CooldownStore, cooldown_keys  # noqa: E402
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
# label-free conditions whose lift is broken down by ProductCD in the EDA consistency check
EDA_CONDITIONS = {
    "foreign_addr2 = 1": ("foreign_addr2", 1),
    "card_age_days = 0 (new card)": ("card_age_days", 0),
    "is_low_volume_window = 1": ("is_low_volume_window", 1),
    "email_mismatch = 1": ("email_mismatch", 1),
    "has_identity = 0": ("has_identity", 0),
}
EDA_GROUP = "ProductCD"


def load_inputs(sfx: str, sample: bool, repo: RuleRepository) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rule inputs (incl. cooldown time + entity columns) and Step 5/6 scores by TransactionID."""
    s = repo.settings
    inp = s.inputs
    feats = pd.read_parquet(PROCESSED_DIR / f"features{sfx}.parquet", columns=inp["features"])
    merged = pd.read_parquet(
        PROCESSED_DIR / f"merged{sfx}.parquet",
        columns=merged_columns(inp["raw"], s.cooldown_columns),
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
    inputs = build_batch_inputs(feats, merged, inp["features"], inp["raw"], s.cooldown_columns)
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


class OnlineReplay:
    """Single-record re-evaluation of batch rows with the cooldown state the online path would
    have at that moment (last kept fire of the entity strictly before the row)."""

    def __init__(self, engine: RuleEngine, inputs: pd.DataFrame, result: pd.DataFrame) -> None:
        s = engine.settings
        self.engine, self.inputs, self.result = engine, inputs, result
        times = inputs[s.time_column].to_numpy("float64")
        pos = np.empty(len(times), dtype=np.int64)
        pos[np.argsort(times, kind="stable")] = np.arange(len(times))  # apply_cooldown order
        keys = cooldown_keys(inputs, s.entity_columns)
        self.state = pd.DataFrame({"time": times, "pos": pos, "key": keys}, index=inputs.index)
        self.fires = {
            r.id: self.state[result[f"{HIT_PREFIX}{r.id}"].to_numpy() == 1]
            for r in engine.active_rules()
            if r.cooldown is not None
        }

    def store_for(self, tid: int) -> CooldownStore:
        """Cooldown state just before row tid."""
        store = CooldownStore()
        me = self.state.loc[tid]
        for rid, fires in self.fires.items():
            prior = fires[(fires["key"] == me["key"]) & (fires["pos"] < me["pos"])]
            if not prior.empty:
                store.set(rid, me["key"], prior.loc[prior["pos"].idxmax(), "time"])
        return store

    def evaluate(self, tid: int):  # noqa: ANN201 - RuleEngineResult
        """Online result for row tid."""
        record = self.inputs.loc[tid].to_dict()
        record[ANOMALY] = float(self.result.at[tid, ANOMALY])
        record[ADJUSTED] = float(self.result.at[tid, ADJUSTED])
        self.engine.cooldown_store = self.store_for(tid)
        return self.engine.evaluate(
            record, float(self.result.at[tid, ADJUSTED_UNCLIPPED]), update_state=False
        )

    def mismatches(self, ids: list) -> int:
        """Rows where the online path disagrees with the batch output."""
        bad = 0
        for tid in ids:
            one = self.evaluate(tid)
            same = (
                one.final_decision == self.result.at[tid, "final_decision"]
                and one.triggered_rules == list(self.result.at[tid, "triggered_rules"])
                and math.isclose(one.final_score_unclipped, self.result.at[tid, FINAL_UNCLIPPED])
            )
            bad += not same
        return bad


def evaluate(
    result: pd.DataFrame,
    inputs: pd.DataFrame,
    engine: RuleEngine,
    parts: dict[str, pd.Index],
    out: Path,
) -> None:
    """Holdout report + fit/holdout EDA consistency check. Labels are read through the loader and
    used only inside src.evaluation functions. Nothing here changes a rule or threshold."""
    from src.data.loader import load_data
    from src.evaluation.rule_metrics import (
        budget_table,
        decision_metrics,
        lift_by_group,
        rule_hit_metrics,
    )

    budgets = load_settings()["evaluation"]["alarm_budgets"]
    _, y_all = load_data()
    rules = engine.active_rules()
    ids = [r.id for r in rules]
    hits = result[[f"{HIT_PREFIX}{rid}" for rid in ids]].set_axis(ids, axis=1).astype(bool)
    applied = pd.DataFrame(
        {rid: result["applied_rules"].map(lambda x, r=rid: r in x) for rid in ids}
    )
    hold = parts["holdout"]
    # stable top-k: equal scores are ranked by the unnormalized Step 5 score (as in Step 6)
    y_hold = y_all.loc[tie_break_order(result.loc[hold, RAW_TIEBREAK])]
    log.info("holdout rows %s, positives %s", len(y_hold), int(y_hold.sum()))

    rule_hit_metrics(y_hold, hits, applied).to_csv(out / "rule_metrics.csv", index=False)
    decision_metrics(y_hold, result["final_decision"]).to_csv(
        out / "decision_metrics.csv", index=False
    )
    scores = {
        "step5 (anomaly_score_norm)": result[ANOMALY],
        "step6 (adjusted_score_unclipped)": result[ADJUSTED_UNCLIPPED],
        "step7 (final_score_unclipped)": result[FINAL_UNCLIPPED],
    }
    table = budget_table(y_hold, scores, budgets)
    table.to_csv(out / "budget_comparison.csv", index=False)
    log.info("budget comparison\n%s", table.to_string(index=False))

    # leave-one-rule-out: same hits, one rule removed before resolution (label-free scores)
    res = result.loc[y_hold.index]
    variants = {}
    for rule in [None, *rules]:
        keep = [r for r in rules if rule is None or r.id != rule.id]
        decided = engine.decide(
            hits.loc[res.index, [r.id for r in keep]], keep, res[ADJUSTED_UNCLIPPED]
        )
        variants["all rules" if rule is None else f"without {rule.id}"] = decided[FINAL_UNCLIPPED]
    abl = budget_table(y_hold, variants, budgets)
    abl.to_csv(out / "rule_ablation.csv", index=False)
    pd.DataFrame(
        [{"n": len(y_hold), "positives": int(y_hold.sum()), "base_rate": float(y_hold.mean())}]
    ).to_csv(out / "holdout_base.csv", index=False)

    # EDA consistency check: the same metrics on FIT rows next to holdout (not used for design)
    side = []
    for part, idx in parts.items():
        m = rule_hit_metrics(y_all.loc[idx], hits).set_index("id")
        side.append(m[["hits", "coverage", "precision", "lift"]].add_prefix(f"{part}_"))
    pd.concat(side, axis=1).reset_index().to_csv(out / "eda_fit_vs_holdout.csv", index=False)
    masks = pd.DataFrame(
        {name: inputs[col].astype("float64") == val for name, (col, val) in EDA_CONDITIONS.items()}
    )
    masks = masks.join(hits.add_prefix("rule "))
    by_product = [
        lift_by_group(y_all.loc[idx], masks, inputs[EDA_GROUP]).assign(part=part)
        for part, idx in parts.items()
    ]
    pd.concat(by_product, ignore_index=True).to_csv(out / "eda_lift_by_product.csv", index=False)


def main() -> int:
    """Run Step 7."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-eval", action="store_true", help="skip labelled evaluation")
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
    fit_part, hold_part = split_by_time(inputs[[repo.settings.time_column]])
    parts = {"fit": fit_part.index, "holdout": hold_part.index}
    log.info("rows %s (fit %s, holdout %s)", len(inputs), len(fit_part), len(hold_part))

    fit_frame = inputs.loc[parts["fit"]].join(scores.loc[parts["fit"]])
    params = learn_params(repo, fit_frame, sample, out)
    del fit_frame
    engine = RuleEngine(repo, params)
    rules = engine.active_rules()
    log.info("active rules: %s", [r.id for r in rules])

    result = engine.evaluate_batch(inputs, scores)
    result.insert(0, RAW_TIEBREAK, scores[RAW_TIEBREAK])
    result.to_parquet(out / "rule_hits.parquet")
    log.info("wrote %s", out / "rule_hits.parquet")

    entity = pd.Series(cooldown_keys(inputs, repo.settings.entity_columns), index=inputs.index)
    rule_coverage(result, rules, parts, entity).to_csv(out / "rule_coverage.csv", index=False)
    decision_distribution(result, parts).to_csv(out / "decision_distribution.csv", index=False)
    pd.concat(
        [conflict_summary(result, idx).assign(part=p) for p, idx in parts.items()],
        ignore_index=True,
    ).to_csv(out / "conflicts.csv", index=False)
    pd.concat(
        [boost_summary(result, idx).assign(part=p) for p, idx in parts.items()], ignore_index=True
    ).to_csv(out / "score_effect.csv", index=False)

    replay = OnlineReplay(engine, inputs, result)
    allow_ids = {r.id for r in rules if r.action.decision == "allow"}
    examples = {}
    # conflicts are rare (high-amount and small-amount rules exclude each other), so examples are
    # picked label-free from all rows; `part` tells where the row comes from
    for tid in pick_conflict_examples(result, result.index, allow_ids, n=5):
        part = "holdout" if tid in parts["holdout"] else "fit"
        examples[str(tid)] = {
            "transaction_id": tid,
            "part": part,
            **replay.evaluate(tid).explain_dict(),
        }
    (out / "conflict_examples.json").write_text(json.dumps(examples, indent=2, ensure_ascii=False))
    log.info("conflict examples: %s", list(examples))

    rng = np.random.default_rng(load_settings()["seed"])
    triggered = result.index[result["triggered_rules"].map(len) > 0]
    cooled = result.index[result["cooldown_rules"].map(len) > 0]
    check_ids = list(rng.choice(result.index, size=min(100, len(result)), replace=False))
    check_ids += list(rng.choice(triggered, size=min(100, len(triggered)), replace=False))
    check_ids += list(rng.choice(cooled, size=min(50, len(cooled)), replace=False))
    mismatches = replay.mismatches(check_ids)
    log.info("batch vs single-record check: %s rows, %s mismatches", len(check_ids), mismatches)
    if mismatches:
        log.error("batch and single-record paths disagree")
        return 1

    if not args.no_eval:
        evaluate(result, inputs, engine, parts, out)
    log.info("done in %.0fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
