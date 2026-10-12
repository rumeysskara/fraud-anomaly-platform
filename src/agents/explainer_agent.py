"""ExplainerAgent: Step 8 RAG explanation for the analyst ("destek bilgisi")."""

from __future__ import annotations

import re
from collections.abc import Callable

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.config import ExplainerConfig
from src.agents.messages import (
    EXPLAINER,
    INTENT_EXPLAIN,
    BusMessage,
    ExplainReply,
    ExplainRequest,
)
from src.agents.timeouts import call_with_timeout
from src.rag.errors import EmbeddingUnavailableError, IndexNotBuiltError
from src.rag.service import CITATION, RAGService

SCORE_SOURCE = "score"  # decision_source of a review that came from the score threshold
RAG_UNAVAILABLE = "rag_unavailable"  # flag: no index or no embedding model, template used


def strip_task_sentences(question: str | None, patterns: list[str]) -> str:
    """Drop sentences that are task instructions ("inceleme notu yaz") from a question."""
    if not question:
        return ""
    regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
    parts = re.split(r"(?<=[.!?])\s+", question.strip())
    return " ".join(p for p in parts if p and not any(r.search(p) for r in regexes))


def is_empty_answer(text: str | None, sources_pattern: str) -> bool:
    """True when the answer is missing or only a source line (citations and 'Kaynaklar:')."""
    if not text:
        return True
    rest = CITATION.sub(" ", text)
    rest = re.sub(sources_pattern, " ", rest, flags=re.IGNORECASE)
    return not re.search(r"\w", rest)


def top_layers(layer_scores: dict[str, float], n: int) -> list[tuple[str, float]]:
    """The n highest layer scores, descending."""
    return sorted(layer_scores.items(), key=lambda kv: kv[1], reverse=True)[:n]


class ExplainerAgent(Agent):
    """Explains a rule result with the knowledge base.

    Triggered rule ids come from the RuleAgent result in the request. The query is built from the
    real reason of the decision (K-39). If the RAG answer is empty or only a source line, a
    template text (decision reason, top layer scores, applied C rules) replaces it and the trace
    gets `explanation_fallback`. The same template is used when retrieval is impossible (index
    not built or embedding model down; flag `rag_unavailable`). Both outputs are labelled as
    supporting information; the reply type has no decision field and the coordinator never reads
    one from it. Other RAG errors and timeouts become an error reply (explanation=null).

    `rag` is a provider (callable) resolved at explain time, so a missing index affects only this
    step: scoring, context and rules still run and the trace is kept (Step 8-10 review, Ö1).
    """

    def __init__(
        self, bus: MessageBus, rag: Callable[[], RAGService], config: ExplainerConfig
    ) -> None:
        super().__init__(EXPLAINER, bus)
        self.rag = rag
        self.config = config
        self.on(INTENT_EXPLAIN, self._explain)

    def build_query(self, request: ExplainRequest) -> str:
        """RAG query: the analyst's knowledge question (task sentences removed) or, when there is
        none, a query about the real reason: triggered rules, or the score threshold."""
        cfg = self.config
        cleaned = strip_task_sentences(request.question, cfg.task_patterns)
        if cleaned:
            return cleaned
        result = request.rule_result
        if not result.triggered_rules and result.decision_source == SCORE_SOURCE:
            names = ", ".join(n for n, _ in top_layers(request.layer_scores, cfg.top_layers))
            return cfg.score_question.format(
                layers=names or "column, multivariate, entity, temporal"
            )
        return cfg.default_question

    def template_text(self, request: ExplainRequest) -> str:
        """Deterministic explanation from the decision reason, layer scores and C rules."""
        result = request.rule_result
        parts = [
            f"Karar: {result.final_decision} (kaynak: {result.decision_source}, "
            f"nihai skor {result.final_score:.3f}).",
            "Karar nedeni: " + (" ".join(result.reasons) or "kayıtlı gerekçe yok."),
        ]
        layers = top_layers(request.layer_scores, self.config.top_layers)
        if layers:
            parts.append(
                "En yüksek katman skorları: " + ", ".join(f"{n} {v:.2f}" for n, v in layers) + "."
            )
        if request.context_rules:
            parts.append("Uygulanan context kuralları: " + ", ".join(request.context_rules) + ".")
        return " ".join(parts)

    def _explain(self, message: BusMessage) -> ExplainReply:
        request = ExplainRequest.model_validate(message.payload)
        result = request.rule_result
        query = self.build_query(request)
        try:
            answer = call_with_timeout(
                lambda: self.rag().answer(
                    query, explanation=result.explain, rule_ids=result.triggered_rules
                ),
                self.config.timeout_seconds,
            )
        except (IndexNotBuiltError, EmbeddingUnavailableError) as exc:
            self.bus.note(message.correlation_id, self.name, "explanation_fallback", str(exc))
            return ExplainReply(
                label=self.config.label,
                text=self.template_text(request),
                origin="template",
                grounded=False,
                flags=[RAG_UNAVAILABLE, "explanation_fallback"],
                warning=f"{type(exc).__name__}: {exc}",
            )
        reply = ExplainReply(
            label=self.config.label,
            text=answer.answer,
            sources=[s.model_dump() for s in answer.sources],
            cited_ids=answer.cited_ids,
            grounded=answer.grounded,
            abstained=answer.abstained,
            flags=answer.flags,
            warning=answer.warning,
        )
        if is_empty_answer(answer.answer, self.config.empty_sources_pattern):
            self.bus.note(
                message.correlation_id,
                self.name,
                "explanation_fallback",
                "RAG answer empty or only a source line; template used",
            )
            reply.text = self.template_text(request)
            reply.origin = "template"
            reply.grounded = False
            reply.cited_ids = []
            reply.flags = [*reply.flags, "explanation_fallback"]
        return reply
