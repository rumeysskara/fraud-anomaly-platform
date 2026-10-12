"""Step 9 demo: run three holdout transactions (block / review / allow) through the agents.

Usage: python scripts/run_agents_demo.py
The three transactions are picked from the HOLDOUT by the rule engine's batch decision only
(reports/rules/rule_hits.parquet); no label is read. The middle row (by TransactionID) of each
decision group is used, skipping rows a cooldown removed (the online store starts empty, so
they could not match). Everything else is the real online path: records are assembled from
data/processed, and the AnomalyAgent, ContextAgent, RuleAgent and ExplainerAgent run through the
bus with the real Ollama models. If Ollama or the RAG index is missing the run still finishes
(default plan, template explanation flagged rag_unavailable/llm_unavailable). Traces:
reports/agents/.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.messages import AgentResponse, AnalystRequest  # noqa: E402
from src.container import Container, create_container  # noqa: E402
from src.context.derive import EMAIL_KNOWN  # noqa: E402
from src.context.inputs import RAW_SOURCE_COLUMNS, email_known_batch  # noqa: E402
from src.core.config import PROCESSED_DIR, REPORTS_DIR, set_seed  # noqa: E402
from src.data.loader import split_by_time  # noqa: E402
from src.detection.aux import AUX_SOURCE_COLUMNS, build_aux  # noqa: E402

log = logging.getLogger("run_agents_demo")
OUT_DIR = REPORTS_DIR / "agents"
DECISIONS = ["block", "review", "allow"]
# Questions: None -> deterministic default plan; the others go to the LLM planner.
QUESTIONS: dict[str, str | None] = {
    "block": None,
    "review": "TransactionID {tid} işlemini incele ve bir inceleme notu yaz.",
    "allow": "TransactionID {tid} işleminin kararı nedir? Açıklama gerekmez, sadece karar.",
}


def pick_transactions(hits: pd.DataFrame, holdout_ids: pd.Index) -> dict[str, int]:
    """Middle TransactionID of each decision group in the holdout (cooldown-free rows)."""
    rows = hits.loc[hits.index.intersection(holdout_ids)]
    rows = rows[rows["cooldown_rules"].map(len) == 0].sort_index()
    return {
        d: int(rows[rows["final_decision"] == d].index[len(rows[rows["final_decision"] == d]) // 2])
        for d in DECISIONS
    }


def build_records(container: Container, tids: list[int]) -> dict[int, dict[str, Any]]:
    """One online-style record per TransactionID: features + raw fields + aux + cooldown keys."""
    settings = container.rule_engine().settings
    merged_cols = list(
        dict.fromkeys(
            [
                *RAW_SOURCE_COLUMNS,
                *AUX_SOURCE_COLUMNS,
                *settings.inputs["raw"],
                *settings.cooldown_columns,
            ]
        )
    )
    merged = pd.read_parquet(PROCESSED_DIR / "merged.parquet", columns=merged_cols)
    known = email_known_batch(merged[RAW_SOURCE_COLUMNS])  # past-only, needs all earlier rows
    feats = pd.read_parquet(PROCESSED_DIR / "features.parquet").loc[tids]
    aux = build_aux(merged.loc[tids, AUX_SOURCE_COLUMNS])
    records = {}
    for tid in tids:
        record = feats.loc[tid].to_dict()
        record.update(merged.loc[tid, merged_cols].to_dict())
        record.update(aux.loc[tid].to_dict())
        record[EMAIL_KNOWN] = int(known.loc[tid])
        record["TransactionID"] = tid
        records[tid] = {k: (None if pd.isna(v) else v) for k, v in record.items()}
    return records


def summarize(response: AgentResponse, batch: pd.Series) -> dict[str, Any]:
    """One-line view of a run for the console and the summary file."""
    return {
        "transaction_id": response.transaction_id,
        "plan": response.plan.model_dump(),
        "decision": response.decision,
        "batch_decision": batch["final_decision"],
        "decision_matches_batch": response.decision == batch["final_decision"],
        "triggered_rules": response.triggered_rules,
        "context_rules": response.context_rules,
        "status": response.status,
        "explanation_present": response.explanation is not None,
        "total_ms": response.total_ms,
        "trace": [
            f"{t.seq}. {t.sender} -> {t.recipient} {t.intent} [{t.status}] {t.duration_ms} ms"
            for t in response.trace
        ],
    }


def main() -> None:
    """Pick three holdout transactions, run the agents, write traces."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    set_seed()
    container = create_container()
    hits = pd.read_parquet(
        REPORTS_DIR / "rules" / "rule_hits.parquet", columns=["final_decision", "cooldown_rules"]
    )
    times = pd.read_parquet(PROCESSED_DIR / "merged.parquet", columns=["TransactionDT"])
    _, holdout = split_by_time(times)
    picks = pick_transactions(hits, holdout.index)
    log.info("picked %s", picks)
    records = build_records(container, list(picks.values()))
    coordinator = container.coordinator()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for decision, tid in picks.items():
        question = QUESTIONS[decision]
        question = question.format(tid=tid) if question else None
        log.info("running %s (%s) question=%r", tid, decision, question)
        response = coordinator.analyze(AnalystRequest(record=records[tid], question=question))
        path = OUT_DIR / f"trace_{decision}_{tid}.json"
        path.write_text(
            json.dumps(
                {"question": question, **response.model_dump(mode="json")},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        summary.append(summarize(response, hits.loc[tid]))
        log.info("wrote %s", path)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
