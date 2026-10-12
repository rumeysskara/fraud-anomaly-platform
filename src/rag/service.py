"""RAGService: retrieve -> prompt -> LLM -> structured answer with sources."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.core.interfaces import LLMClient, Retriever
from src.core.types import Chunk
from src.rag.errors import LLMUnavailableError
from src.rag.prompt import PromptBuilder

logger = logging.getLogger(__name__)

LLM_UNAVAILABLE = "llm_unavailable"


class SourceRef(BaseModel):
    """A retrieved chunk shown as a source."""

    chunk_id: str
    heading: str
    doc_type: str = ""
    rule_ids: list[str] = Field(default_factory=list)
    score: float = 0.0
    retrieval: str = ""


class RAGAnswer(BaseModel):
    """Structured RAG output. answer is None when the LLM is unavailable (retrieval-only)."""

    question: str
    answer: str | None
    sources: list[SourceRef]
    cited_ids: list[str] = Field(default_factory=list)
    used_context: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class RAGService:
    """Answers analyst questions from the knowledge base with a local LLM.

    Embedding failure raises EmbeddingUnavailableError (nothing can be retrieved). LLM failure
    degrades to a retrieval-only answer with the 'llm_unavailable' flag.
    """

    def __init__(self, retriever: Retriever, llm: LLMClient, prompt_builder: PromptBuilder) -> None:
        self.retriever = retriever
        self.llm = llm
        self.prompt_builder = prompt_builder

    def answer(
        self,
        question: str,
        explanation: dict[str, Any] | None = None,
        rule_ids: list[str] | None = None,
        k: int | None = None,
    ) -> RAGAnswer:
        """Answer `question`; `explanation` is a rule engine explain_dict (optional).

        Triggered rule ids come from `rule_ids` or, when absent, from the explanation.
        """
        ids = rule_ids if rule_ids is not None else triggered_rule_ids(explanation)
        filters = {"rule_ids": ids} if ids else None
        if k is None:
            chunks = self.retriever.retrieve(question, filters=filters)
        else:
            chunks = self.retriever.retrieve(question, k, filters)
        sources = [_source(c) for c in chunks]
        used = [c.text for c in chunks]
        context = self.prompt_builder.build_context(chunks)
        user = self.prompt_builder.build_user(question, explanation)
        try:
            text: str | None = self.llm.generate(user, context)
        except LLMUnavailableError as exc:
            logger.warning("LLM unavailable, returning retrieval only: %s", exc)
            return RAGAnswer(
                question=question,
                answer=None,
                sources=sources,
                used_context=used,
                flags=[LLM_UNAVAILABLE],
            )
        cited = [s.chunk_id for s in sources if text and s.chunk_id in text]
        return RAGAnswer(
            question=question, answer=text, sources=sources, cited_ids=cited, used_context=used
        )


def triggered_rule_ids(explanation: dict[str, Any] | None) -> list[str]:
    """Rule ids from a rule engine explain_dict ('triggered_rules': list of dicts or ids)."""
    if not explanation:
        return []
    ids = []
    for item in explanation.get("triggered_rules", []):
        ids.append(str(item["id"]) if isinstance(item, dict) else str(item))
    return list(dict.fromkeys(ids))


def _source(chunk: Chunk) -> SourceRef:
    meta = chunk.metadata
    return SourceRef(
        chunk_id=meta["chunk_id"],
        heading=" > ".join(meta.get("heading_path", [])),
        doc_type=meta.get("doc_type", ""),
        rule_ids=list(meta.get("rule_ids", [])),
        score=round(chunk.score, 4),
        retrieval=meta.get("retrieval", ""),
    )
