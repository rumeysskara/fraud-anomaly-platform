"""RuleAgent: Step 7 rule engine. The only source of the final decision."""

from __future__ import annotations

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.messages import (
    CONTEXT,
    INTENT_ADJUST,
    INTENT_EVALUATE,
    RULE,
    AdjustReply,
    AdjustRequest,
    BusMessage,
    EvaluateReply,
    EvaluateRequest,
)
from src.rules.engine import RuleEngine


class RuleAgent(Agent):
    """Evaluates the rules for one record.

    When the request carries no adjusted score it asks the ContextAgent (which in turn asks the
    AnomalyAgent), so the agent works with a minimal plan.
    update_state=False (K-35): analysing a transaction does not write the online cooldown store.
    """

    def __init__(self, bus: MessageBus, engine: RuleEngine, update_state: bool = False) -> None:
        super().__init__(RULE, bus)
        self.engine = engine
        self.update_state = update_state
        self.on(INTENT_EVALUATE, self._evaluate)

    def _evaluate(self, message: BusMessage) -> EvaluateReply:
        request = EvaluateRequest.model_validate(message.payload)
        anomaly, adjusted = request.anomaly_score, request.adjusted_score
        unclipped = request.adjusted_score_unclipped
        layers: dict[str, float] = request.layer_scores or {}
        context_rules: list[str] = []
        if anomaly is None or adjusted is None or unclipped is None:
            ask = AdjustRequest(
                record=request.record,
                anomaly_score=request.anomaly_score,
                layer_scores=request.layer_scores,
            )
            ctx = AdjustReply.model_validate(self.delegate(CONTEXT, INTENT_ADJUST, ask, message))
            anomaly, adjusted = ctx.anomaly_score, ctx.adjusted_score
            unclipped, layers, context_rules = (
                ctx.adjusted_score_unclipped,
                ctx.layer_scores,
                ctx.applied_rules,
            )
        record = {**request.record, "anomaly_score": anomaly, "adjusted_score": adjusted}
        result = self.engine.evaluate(record, unclipped, update_state=self.update_state)
        return EvaluateReply(
            final_decision=result.final_decision,
            decision_source=result.decision_source,
            final_score=result.final_score,
            triggered_rules=result.triggered_rules,
            applied_rules=result.applied_rules,
            suppressed_rules=result.suppressed_rules,
            reasons=result.reasons,
            explain=result.explain_dict(),
            anomaly_score=anomaly,
            adjusted_score=adjusted,
            layer_scores=layers,
            context_rules=context_rules,
        )
