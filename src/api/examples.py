"""Generate examples/requests/*.json: ready-made API bodies taken from the holdout.

    python -m src.api.examples            # full artifacts (SAMPLE_N=50000 for the sample ones)

Rows are chosen only by the BATCH `final_decision` in reports/rules/rule_hits.parquet (a rule
output, not a label). The body gets a fresh TransactionID. Its original time is kept (card
testing needs the streak just before it); if the online decision then differs, the same row is tried
with a time after the end of the data. A candidate is kept only when the online decision equals the
batch decision, so each file demonstrates what its name says. No label is read.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pandas as pd

from src.api.consistency import (
    HISTORY_COLUMNS,
    _payload,
    api_columns,
    build_scorer,
    rewind_to_fit_end,
)
from src.core.config import PROCESSED_DIR, REPORTS_DIR, ROOT_DIR, get_sample_n, set_seed
from src.data.loader import split_by_time

logger = logging.getLogger(__name__)

OUT_DIR = ROOT_DIR / "examples" / "requests"
FIRST_ID = 91_000_000
MAX_TRIES = 60  # candidates tried per decision

INVALID_RULES: dict[str, Any] = {
    "rules": [
        {
            "id": "X01",
            "name": "broken_rule",
            "priority": 0,
            "severity": "urgent",
            "condition": {"all": [{"feature": "no_such_feature", "op": "~", "value": 1}]},
            "action": {"decision": "freeze"},
        }
    ]
}


def _dump(name: str, body: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop null fields so the example stays readable."""
    return {k: v for k, v in payload.items() if v is not None}


def build_examples(sample: bool) -> dict[str, dict[str, Any]]:
    """Pick one verified holdout transaction per decision; return {file name: body}."""
    set_seed()
    sfx, sub = ("_sample", "sample") if sample else ("", "")
    path = PROCESSED_DIR / f"merged{sfx}.parquet"
    slim = pd.read_parquet(path, columns=HISTORY_COLUMNS)
    fit, holdout = split_by_time(slim)
    hours = pd.read_parquet(PROCESSED_DIR / f"features{sfx}.parquet", columns=["hour"])["hour"]
    hits = pd.read_parquet(REPORTS_DIR / "rules" / sub / "rule_hits.parquet")
    frame = pd.read_parquet(path, columns=api_columns(path))
    last_dt = int(slim["TransactionDT"].max())
    day = 86400
    next_day_start = (last_dt // day + 2) * day

    scorer = build_scorer(sample)
    rewind_to_fit_end(scorer, fit, hours.loc[fit.index])
    for tid in holdout.index:  # live history = fit + holdout, like the saved snapshot
        scorer.append_history(_payload(holdout, int(tid)), int(hours.at[tid]))

    eligible = holdout.index[hits.loc[holdout.index, "cooldown_rules"].map(len) == 0]
    found: dict[str, dict[str, Any]] = {}
    next_id = FIRST_ID
    for decision in ("block", "review", "allow"):
        ids = eligible[hits.loc[eligible, "final_decision"] == decision]
        picks = ids[np.linspace(0, len(ids) - 1, min(MAX_TRIES, len(ids))).astype(int)]
        for tid in picks:
            for shift in (False, True):  # block rules need the original time (recent streak)
                payload = _payload(frame, int(tid))
                payload["TransactionID"] = next_id
                next_id += 1
                if shift:
                    payload["TransactionDT"] = next_day_start + int(payload["TransactionDT"]) % day
                outcome = scorer.analyze(dict(payload))[1]
                if outcome.rule.final_decision == decision:
                    found[decision] = _clean(payload)
                    break
            if decision in found:
                break
        else:
            raise RuntimeError(f"no verified {decision} example among {len(picks)} candidates")
    return {
        "block.json": found["block"],
        "review.json": found["review"],
        "allow.json": found["allow"],
        "explain_review.json": {"transaction": found["review"], "question": None},
        "explain_question.json": {
            "transaction": found["block"],
            "question": "Bu işlem neden bloklandı?",
        },
        "rules_invalid.json": {"transaction": found["review"], **INVALID_RULES},
        "rag_query.json": {"question": "Kart testi hangi koşulda tetiklenir?", "k": 4},
    }


def main() -> None:
    """CLI entry."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for name, body in build_examples(sample=get_sample_n() is not None).items():
        _dump(name, body)
        logger.info("wrote %s", OUT_DIR / name)


if __name__ == "__main__":
    main()
