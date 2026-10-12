"""RAGService: retrieve -> prompt -> LLM -> structured answer with sources."""

from __future__ import annotations

import logging
import re
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
    abstained: bool = False  # True: no answer from the knowledge base (LLM may not have run)
    grounded: bool = False  # True: the answer cites only retrieved chunks, and at least one
    top_score: float | None = None  # best unfiltered semantic cosine of the question
    warning: str | None = None


CITATION = re.compile(r"\[([^\[\]\s]+#[^\[\]\s]+)\]")


class RAGService:
    """Answers analyst questions from the knowledge base with a local LLM.

    Embedding failure raises EmbeddingUnavailableError (nothing can be retrieved). LLM failure
    degrades to a retrieval-only answer with the 'llm_unavailable' flag.
    """

    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        prompt_builder: PromptBuilder,
        abstain_threshold: float = 0.0,
        abstain_answer: str = "Bilgi tabanında bu konuda bilgi yok",
        ungrounded_warning: str = "",
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.prompt_builder = prompt_builder
        self.abstain_threshold = abstain_threshold
        self.abstain_answer = abstain_answer
        self.ungrounded_warning = ungrounded_warning

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
        top_score = chunks[0].metadata.get("top_semantic_score", 0.0) if chunks else 0.0
        if self.abstain_threshold > 0 and top_score < self.abstain_threshold:
            # Off-topic question: the best semantic match is too weak, do not call the LLM.
            # The top score ignores metadata-boosted rule cards, so they cannot mask this.
            return RAGAnswer(
                question=question,
                answer=self.abstain_answer,
                sources=[],
                abstained=True,
                top_score=round(top_score, 4),
            )
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
                top_score=round(top_score, 4),
            )
        return self._check(question, text or "", sources, used, top_score)

    def _check(
        self, question: str, text: str, sources: list[SourceRef], used: list[str], top: float
    ) -> RAGAnswer:
        """Source check: every cited id must be a retrieved chunk and at least one is cited."""
        retrieved = {s.chunk_id for s in sources}
        cited = list(dict.fromkeys(CITATION.findall(text)))
        unknown = [c for c in cited if c not in retrieved]
        abstained = self.abstain_answer.lower() in text.lower()
        grounded = bool(cited) and not unknown and not abstained
        warning = None
        if not grounded and not abstained:
            warning = self.ungrounded_warning or "ungrounded answer"
            text = f"{text}\n\n{warning}"
        if abstained:  # the model refused: drop any leftover citations
            return RAGAnswer(
                question=question,
                answer=self.abstain_answer,
                sources=[],
                abstained=True,
                top_score=round(top, 4),
            )
        return RAGAnswer(
            question=question,
            answer=text,
            sources=sources,
            cited_ids=[c for c in cited if c in retrieved],
            used_context=used,
            abstained=False,
            grounded=grounded,
            top_score=round(top, 4),
            warning=warning,
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
