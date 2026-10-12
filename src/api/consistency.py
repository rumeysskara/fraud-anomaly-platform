"""Batch = online check: score holdout transactions through the API code and compare with the
batch outputs (reports/rules/rule_hits.parquet, reports/scores/layer_scores.parquet).

    SAMPLE_N=50000 python -m src.api.consistency      # sample artifacts
    python -m src.api.consistency                     # full artifacts

How it works (no label is read): the online histories (entity store, hour store) are rebuilt as
they were at the end of the fit set, then the holdout is walked in time order. Rows that are not
checked only append to the history (fast-forward); the `n` checked rows, spread evenly over the
holdout, go through `OnlineScorer.score`, exactly like POST /score. Rows a cooldown removed in
the batch run are not checked because the online cooldown store starts empty here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from src.api.config import ApiSettings
from src.api.mappers import to_score_response
from src.api.online import OnlineScorer
from src.api.schemas import EXTRA_COLUMN, TransactionIn
from src.context.factory import load_engine, params_directory
from src.core.config import (
    ARTIFACTS_DIR,
    CONFIG_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    get_sample_n,
    set_seed,
)
from src.data.loader import split_by_time
from src.detection.aux import AUX_SOURCE_COLUMNS, build_aux
from src.features.pipeline import FeaturePipeline
from src.rules.cooldown import CooldownStore
from src.rules.factory import load_rule_engine
from src.rules.repository import RuleRepository
from src.scoring.service import ScoringService

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = ["TransactionDT", "TransactionAmt", *AUX_SOURCE_COLUMNS, "P_emaildomain"]
# default tolerance for score columns (batch stores float32 features, online uses float64 input)
ATOL = 1e-3


def build_scorer(sample: bool) -> OnlineScorer:
    """OnlineScorer from the saved artifacts (sample or full), with empty cooldown state."""
    sfx = "_sample" if sample else ""
    detectors = ARTIFACTS_DIR / "detectors" / ("sample" if sample else "")
    pipeline = FeaturePipeline.load(ARTIFACTS_DIR / f"feature_pipeline{sfx}.joblib")
    scoring = ScoringService.load(detectors)
    from src.context.config import load_context_config

    adjuster = load_engine(detectors, params_directory(load_context_config(), sample))
    engine = load_rule_engine(
        RuleRepository(CONFIG_DIR / "rules.yaml"),
        CooldownStore(),
        sample=sample,
        sample_dir=REPORTS_DIR / "rules" / "sample",
    )
    return OnlineScorer(pipeline, scoring, adjuster, engine, ApiSettings())


def api_columns(path: Any) -> list[str]:
    """Columns of a merged parquet that the API accepts as input."""
    names = pq.read_schema(path).names
    return [n for n in names if n in TransactionIn.model_fields or EXTRA_COLUMN.match(n)]


def _payload(frame: pd.DataFrame, tid: int) -> dict[str, Any]:
    row = frame.loc[tid]
    clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
    clean = {k: (v.item() if hasattr(v, "item") else v) for k, v in clean.items()}
    clean["TransactionID"] = int(tid)
    return clean


def rewind_to_fit_end(scorer: OnlineScorer, slim: pd.DataFrame, hours: pd.Series) -> None:
    """Rebuild the entity store and the hour store as they were after the last fit row."""
    scorer.pipeline.build_store(slim)
    temporal = scorer.scoring.detectors["temporal"]
    hour_df = build_aux(slim)[["entity_key"]].join(hours.rename("hour"))
    temporal.build_store(hour_df)


ScoreFn = Callable[[dict[str, Any]], dict[str, Any]]


def direct_score_fn(scorer: OnlineScorer) -> ScoreFn:
    """Call OnlineScorer.score and return the /score response body as a dict."""

    def call(payload: dict[str, Any]) -> dict[str, Any]:
        outcome, duplicate, latency = scorer.score(payload)
        return to_score_response(outcome, duplicate, latency).model_dump()

    return call


def pick_rows(decisions: pd.Series, n: int, spread: bool) -> pd.Index:
    """Rows to check, in time order. spread=False: the first n. spread=True: spread evenly over
    the holdout and stratified by the BATCH decision (5 block, 5 review, the rest allow) so that
    non-allow decisions are covered; the batch decision is an output of the rules, not a label."""
    if not spread:
        return decisions.index[:n]
    per_group = {"block": n // 4, "review": n // 4}
    chosen: list[int] = []
    for decision, count in [*per_group.items(), ("allow", n - 2 * (n // 4))]:
        ids = decisions.index[decisions == decision]
        if len(ids):
            take = min(count, len(ids))
            chosen += [int(i) for i in ids[np.linspace(0, len(ids) - 1, take).astype(int)]]
    rest = decisions.index.difference(pd.Index(chosen))  # groups smaller than asked: fill up
    chosen += [int(i) for i in rest[: max(0, n - len(chosen))]]
    return pd.Index(sorted(chosen))


def run_check(
    sample: bool,
    n: int = 20,
    spread: bool = True,
    make_score_fn: Callable[[OnlineScorer], ScoreFn] = direct_score_fn,
) -> pd.DataFrame:
    """Score `n` holdout transactions online; return the comparison with the batch output.

    spread=True: the n rows are spread over the whole holdout (slow on full data: every other
    holdout row is replayed into the history). spread=False: the first n eligible rows in time
    order; the rows before them are scored too, so the history stays exact (fast).
    """
    set_seed()
    sfx, sub = ("_sample", "sample") if sample else ("", "")
    path = PROCESSED_DIR / f"merged{sfx}.parquet"
    slim = pd.read_parquet(path, columns=HISTORY_COLUMNS)
    fit, holdout = split_by_time(slim)
    hours = pd.read_parquet(PROCESSED_DIR / f"features{sfx}.parquet", columns=["hour"])["hour"]
    hits = pd.read_parquet(REPORTS_DIR / "rules" / sub / "rule_hits.parquet")
    layers = pd.read_parquet(REPORTS_DIR / "scores" / sub / "layer_scores.parquet")

    eligible = holdout.index[hits.loc[holdout.index, "cooldown_rules"].map(len) == 0]
    picks = pick_rows(hits.loc[eligible, "final_decision"], n, spread)
    scorer = build_scorer(sample)
    rewind_to_fit_end(scorer, fit, hours.loc[fit.index])
    pick_set = {int(t) for t in picks}
    score_fn = make_score_fn(scorer)
    order = [int(t) for t in holdout.index]
    upto = order[: order.index(int(picks[-1])) + 1]  # nothing after the last checked row matters
    wanted = pick_set if spread else set(upto)  # rows that go through score()
    full = pd.read_parquet(path, columns=api_columns(path)).loc[sorted(wanted)]

    rows = []
    for tid in upto:
        if tid not in wanted:  # fast-forward: history only
            scorer.append_history(_payload(holdout, tid), int(hours.at[tid]))
            continue
        response = score_fn(_payload(full, tid))
        if tid not in pick_set:
            continue
        batch = hits.loc[tid]
        rows.append(
            {
                "TransactionID": tid,
                "anomaly_online": response["anomaly_score"],
                "anomaly_batch": float(batch["anomaly_score"]),
                "adjusted_online": response["adjusted_score"],
                "adjusted_batch": float(batch["adjusted_score"]),
                "final_online": response["final_score"],
                "final_batch": float(batch["final_score"]),
                "decision_online": response["final_decision"],
                "decision_batch": batch["final_decision"],
                "layer_max_abs_diff": max(
                    abs(response["layer_scores"][k] - float(layers.at[tid, f"{k}_score"]))
                    for k in response["layer_scores"]
                ),
                "rules_match": [r["id"] for r in response["triggered_rules"]]
                == list(batch["triggered_rules"]),
            }
        )
    return pd.DataFrame(rows).set_index("TransactionID")


def summarize(result: pd.DataFrame, atol: float = ATOL) -> dict[str, Any]:
    """Max differences and the number of rows that do not match within tolerance."""
    diffs = {
        c: float((result[f"{c}_online"] - result[f"{c}_batch"]).abs().max())
        for c in ("anomaly", "adjusted", "final")
    }
    bad = (
        (result["decision_online"] != result["decision_batch"])
        | ~result["rules_match"]
        | (result["layer_max_abs_diff"] > atol)
        | any_over(result, atol)
    )
    return {
        "rows": len(result),
        "max_abs_diff": {**diffs, "layers": float(result["layer_max_abs_diff"].max())},
        "mismatching_rows": int(bad.sum()),
        "decision_changes": int((result["decision_online"] != result["decision_batch"]).sum()),
        "atol": atol,
    }


def any_over(result: pd.DataFrame, atol: float) -> pd.Series:
    """Rows where any score column differs by more than atol."""
    over = pd.Series(False, index=result.index)
    for c in ("anomaly", "adjusted", "final"):
        over |= (result[f"{c}_online"] - result[f"{c}_batch"]).abs() > atol
    return over


def main() -> None:
    """CLI: print the comparison and the summary."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    result = run_check(sample=get_sample_n() is not None)
    pd.set_option("display.width", 200)
    print(result.round(5).to_string())
    print(summarize(result))


if __name__ == "__main__":
    main()
