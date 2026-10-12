"""API services behind /explain and /rag/query: deadlines and llm_status handling."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.agents.coordinator import CoordinatorAgent
from src.agents.errors import AgentTimeout
from src.agents.messages import AgentResponse, AnalystRequest
from src.agents.timeouts import call_with_timeout
from src.api.config import ApiSettings
from src.api.mappers import (
    classify_llm,
    to_agent_info,
    to_facts,
    to_narrative,
    trace_dicts,
)
from src.api.online import OnlineScorer
from src.api.schemas import ExplainResponse, LlmStatus, RagQueryResponse
from src.rag.errors import EmbeddingUnavailableError, LLMUnavailableError
from src.rag.service import LLM_UNAVAILABLE, RAGService

logger = logging.getLogger(__name__)


class ExplainService:
    """/explain: deterministic facts from the scorer, narrative from the Step 9 agent flow.

    The facts never depend on the LLM. The agent flow (planner, RAG) runs second; if it fails or
    is slow the response still carries the facts, narrative=null and an llm_status. No state is
    written (the rule engine is called with update_state=False, K-35).
    """

    def __init__(self, scorer: OnlineScorer, coordinator: CoordinatorAgent) -> None:
        self.scorer = scorer
        self.coordinator = coordinator

    def explain(self, txn: dict[str, Any], question: str | None) -> ExplainResponse:
        """Facts + optional narrative + trace for one transaction."""
        started = time.perf_counter()
        _, outcome = self.scorer.analyze(txn)
        facts = to_facts(outcome, self.scorer.thresholds())
        response: AgentResponse | None = None
        error: str | None = None
        try:
            # the raw transaction goes to the agents: the AnomalyAgent asks the FeatureAgent for
            # the record (K-54), which reads the same record as `analyze` above (record_for)
            request = AnalystRequest(transaction=dict(txn), question=question)
            response = self.coordinator.analyze(request)
        except Exception as exc:  # noqa: BLE001 - the facts must still be returned
            logger.warning("agent flow failed: %s", exc)
            error = f"{type(exc).__name__}: {exc}"
        return ExplainResponse(
            transaction_id=outcome.transaction_id,
            facts=facts,
            narrative=to_narrative(response),
            llm_status=classify_llm(response, error),
            agent=to_agent_info(response),
            trace=trace_dicts(response),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


class RagQueryService:
    """/rag/query: RAGService with a deadline; LLM or embedding problems become llm_status."""

    def __init__(self, rag: RAGService, settings: ApiSettings) -> None:
        self.rag = rag
        self.settings = settings

    def query(self, question: str, k: int | None, rule_ids: list[str]) -> RagQueryResponse:
        """Answer from the knowledge base; never raises for an unavailable LLM or timeout."""
        started = time.perf_counter()
        k = None if k is None else min(k, self.settings.rag.max_k)
        status: LlmStatus = "ok"
        answer = None
        try:
            answer = call_with_timeout(
                lambda: self.rag.answer(question, rule_ids=rule_ids or None, k=k),
                self.settings.llm.timeout_seconds,
            )
        except AgentTimeout:
            status = "timeout"
        except (EmbeddingUnavailableError, LLMUnavailableError) as exc:
            logger.warning("rag unavailable: %s", exc)
            status = "unavailable"
        latency = round((time.perf_counter() - started) * 1000, 2)
        if answer is None:
            flags = ["llm_unavailable"] if status == "unavailable" else [status]
            return RagQueryResponse(
                question=question,
                answer=None,
                sources=[],
                abstained=False,
                grounded=False,
                llm_status=status,
                flags=flags,
                latency_ms=latency,
            )
        if LLM_UNAVAILABLE in answer.flags:
            status = "unavailable"
        return RagQueryResponse(
            question=question,
            answer=answer.answer,
            sources=[s.model_dump() for s in answer.sources],
            abstained=answer.abstained,
            grounded=answer.grounded,
            llm_status=status,
            flags=answer.flags,
            warning=answer.warning,
            latency_ms=latency,
        )
