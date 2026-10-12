"""ExplainerAgent: Step 8 RAG explanation for the analyst ("destek bilgisi")."""

from __future__ import annotations

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
from src.rag.service import RAGService


class ExplainerAgent(Agent):
    """Explains a rule result with the knowledge base.

    Triggered rule ids come from the RuleAgent result in the request. The output is labelled as
    supporting information and has no way to touch the decision: the reply type has no decision
    field and the coordinator never reads one from it. RAG or timeout errors become an error
    reply (explanation=null in the response).
    """

    def __init__(self, bus: MessageBus, rag: RAGService, config: ExplainerConfig) -> None:
        super().__init__(EXPLAINER, bus)
        self.rag = rag
        self.config = config
        self.on(INTENT_EXPLAIN, self._explain)

    def _explain(self, message: BusMessage) -> ExplainReply:
        request = ExplainRequest.model_validate(message.payload)
        result = request.rule_result
        question = request.question or self.config.default_question
        answer = call_with_timeout(
            lambda: self.rag.answer(
                question, explanation=result.explain, rule_ids=result.triggered_rules
            ),
            self.config.timeout_seconds,
        )
        return ExplainReply(
            label=self.config.label,
            text=answer.answer,
            sources=[s.model_dump() for s in answer.sources],
            cited_ids=answer.cited_ids,
            grounded=answer.grounded,
            abstained=answer.abstained,
            flags=answer.flags,
            warning=answer.warning,
        )
