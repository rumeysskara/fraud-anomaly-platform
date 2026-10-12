"""Retrieval accuracy: hit@k over questions with an expected rule id / document type."""

from __future__ import annotations

from typing import Any

from src.core.interfaces import Retriever
from src.core.types import Chunk


def matches(chunk: Chunk, expect: dict[str, Any]) -> bool:
    """True when the chunk satisfies every key of `expect` (rule_id, doc_type, chunk_id)."""
    meta = chunk.metadata
    if "rule_id" in expect and expect["rule_id"] not in meta.get("rule_ids", []):
        return False
    if "doc_type" in expect and meta.get("doc_type") != expect["doc_type"]:
        return False
    return not ("chunk_id" in expect and meta.get("chunk_id") != expect["chunk_id"])


def first_hit_rank(chunks: list[Chunk], expect: dict[str, Any]) -> int | None:
    """1-based rank of the first matching chunk, or None."""
    for rank, chunk in enumerate(chunks, start=1):
        if matches(chunk, expect):
            return rank
    return None


def evaluate_retrieval(
    retriever: Retriever, questions: list[dict[str, Any]], ks: tuple[int, ...] = (1, 3, 5)
) -> dict[str, Any]:
    """Run pure semantic retrieval (no filters) and compute hit@k for each k.

    Returns {"hit_at_k": {k: share}, "rows": [{question, expect, rank}]}.
    """
    top = max(ks)
    rows = []
    for item in questions:
        chunks = retriever.retrieve(item["question"], top)
        out_of_kb = bool(item["expect"].get("out_of_kb"))
        rows.append(
            {
                "question": item["question"],
                "expect": item["expect"],
                "out_of_kb": out_of_kb,
                "top_score": chunks[0].metadata["top_semantic_score"] if chunks else 0.0,
                "rank": None if out_of_kb else first_hit_rank(chunks, item["expect"]),
                "retrieved": [c.metadata["chunk_id"] for c in chunks],
            }
        )
    in_kb = [r for r in rows if not r["out_of_kb"]]
    hit = {k: sum(1 for r in in_kb if r["rank"] and r["rank"] <= k) / len(in_kb) for k in ks}
    return {"hit_at_k": hit, "rows": rows}


def abstain_rates(rows: list[dict[str, Any]], threshold: float) -> dict[str, float]:
    """Correct-abstain rate (out-of-KB questions) and false-abstain rate (in-KB questions)."""
    out = [r for r in rows if r["out_of_kb"]]
    inside = [r for r in rows if not r["out_of_kb"]]
    return {
        "correct_abstain": sum(r["top_score"] < threshold for r in out) / max(len(out), 1),
        "false_abstain": sum(r["top_score"] < threshold for r in inside) / max(len(inside), 1),
    }
