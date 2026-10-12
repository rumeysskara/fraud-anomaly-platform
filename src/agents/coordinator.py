"""CoordinatorAgent: takes the request, plans, delegates through the bus and merges the results."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.messages import (
    ANOMALY,
    CLIENT,
    CONTEXT,
    COORDINATOR,
    EXPLAINER,
    INTENT_ANALYZE,
    RULE,
    AdjustReply,
    AdjustRequest,
    AgentResponse,
    AnalystRequest,
    BusMessage,
    EvaluateReply,
    EvaluateRequest,
    ExplainReply,
    ExplainRequest,
    PlanInfo,
    ScoreReply,
    ScoreRequest,
)
from src.agents.planner import Planner

logger = logging.getLogger(__name__)


class CoordinatorAgent(Agent):
    """Runs the plan step by step. The decision is copied from the RuleAgent reply only.

    A failing helper (anomaly, context, explainer) is recorded in `errors` and the request goes
    on; the rule step then asks for missing scores itself. If the rule step fails there is no
    decision (status=error); the coordinator never invents one.
    """

    def __init__(self, bus: MessageBus, planner: Planner) -> None:
        super().__init__(COORDINATOR, bus)
        self.planner = planner
        self.on(INTENT_ANALYZE, self._analyze)

    def analyze(self, request: AnalystRequest) -> AgentResponse:
        """Public entry: send the request through the bus and return the response with its trace."""
        message = BusMessage(
            sender=CLIENT,
            recipient=COORDINATOR,
            intent=INTENT_ANALYZE,
            payload=request.model_dump(),
        )
        reply = self.bus.send(message)
        trace = self.bus.pop_trace(message.correlation_id)
        if reply.status != "ok":  # the coordinator itself failed
            return AgentResponse(
                correlation_id=message.correlation_id,
                status="error",
                plan=PlanInfo(source="default", steps=[]),
                errors=[str(reply.payload.get("error", "coordinator failed"))],
                trace=trace,
            )
        response = AgentResponse.model_validate(reply.payload)
        response.trace = trace
        return response

    def _analyze(self, message: BusMessage) -> AgentResponse:
        started = time.perf_counter()
        request = AnalystRequest.model_validate(message.payload)
        plan = self.planner.plan(request.question)
        if plan.fallback_reason:
            self.bus.note(
                message.correlation_id, COORDINATOR, "plan_fallback", plan.fallback_reason
            )
        state: dict[str, Any] = {}
        errors: list[str] = []
        for step in plan.steps:
            agent, intent = step.split(":")
            try:
                state[agent] = self._run_step(agent, intent, request, state, message)
            except Exception as exc:  # noqa: BLE001 - degrade, do not crash the request
                errors.append(f"{step}: {exc}")
        response = self._merge(message, request, plan, state, errors)
        response.total_ms = round((time.perf_counter() - started) * 1000, 2)
        return response

    def _run_step(
        self,
        agent: str,
        intent: str,
        request: AnalystRequest,
        state: dict[str, Any],
        parent: BusMessage,
    ) -> Any:
        """Send one plan step with the results gathered so far; return the validated reply."""
        record = request.record
        score: ScoreReply | None = state.get(ANOMALY)
        adjusted: AdjustReply | None = state.get(CONTEXT)
        base = adjusted or score  # both carry anomaly_score and layer_scores
        if agent == ANOMALY:
            payload, model = ScoreRequest(record=record), ScoreReply
        elif agent == CONTEXT:
            payload = AdjustRequest(
                record=record,
                anomaly_score=score.anomaly_score if score else None,
                layer_scores=score.layer_scores if score else None,
            )
            model = AdjustReply
        elif agent == RULE:
            payload = EvaluateRequest(
                record=record,
                anomaly_score=base.anomaly_score if base else None,
                layer_scores=base.layer_scores if base else None,
                adjusted_score=adjusted.adjusted_score if adjusted else None,
                adjusted_score_unclipped=adjusted.adjusted_score_unclipped if adjusted else None,
            )
            model = EvaluateReply
        else:  # explainer: needs the rule result (plan order guarantees it ran before)
            if RULE not in state:
                raise RuntimeError("no rule result to explain")
            payload = ExplainRequest(rule_result=state[RULE], question=request.question)
            model = ExplainReply
        return model.model_validate(self.delegate(agent, intent, payload, parent))

    def _merge(
        self,
        message: BusMessage,
        request: AnalystRequest,
        plan: PlanInfo,
        state: dict[str, Any],
        errors: list[str],
    ) -> AgentResponse:
        rule: EvaluateReply | None = state.get(RULE)
        adjusted: AdjustReply | None = state.get(CONTEXT)
        score: ScoreReply | None = state.get(ANOMALY)
        explanation: ExplainReply | None = state.get(EXPLAINER)
        tid = request.record.get("TransactionID")
        response = AgentResponse(
            correlation_id=message.correlation_id,
            transaction_id=int(tid) if tid is not None else None,
            status="error" if rule is None else ("degraded" if errors else "ok"),
            plan=plan,
            errors=errors,
            explanation=explanation,
        )
        if score is not None:
            response.anomaly_score = score.anomaly_score
            response.layer_scores = score.layer_scores
        if adjusted is not None:
            response.anomaly_score = adjusted.anomaly_score
            response.layer_scores = adjusted.layer_scores
            response.adjusted_score = adjusted.adjusted_score
            response.context_rules = adjusted.applied_rules
        if rule is not None:  # the decision comes from here and only from here
            if adjusted is None:  # the rule agent fetched the scores itself (delegation)
                response.anomaly_score = rule.anomaly_score
                response.layer_scores = rule.layer_scores
                response.adjusted_score = rule.adjusted_score
                response.context_rules = rule.context_rules
            response.decision = rule.final_decision
            response.decision_source = rule.decision_source
            response.final_score = rule.final_score
            response.triggered_rules = rule.triggered_rules
            response.suppressed_rules = rule.suppressed_rules
            response.reasons = rule.reasons
        return response
