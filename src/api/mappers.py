"""Turn service results into API models (pure functions, no state)."""

from __future__ import annotations

from typing import Any

from src.agents.messages import AgentResponse
from src.api.online import ScoreOutcome
from src.api.schemas import (
    AgentInfo,
    ContextRuleOut,
    Facts,
    LlmStatus,
    Narrative,
    ScoreResponse,
    SuppressedRuleOut,
    Thresholds,
    TriggeredRuleOut,
)

TOP_LAYERS = 2  # layers named in the template summary


def _context(outcome: ScoreOutcome) -> list[ContextRuleOut]:
    return [
        ContextRuleOut(
            id=str(e["id"]),
            name=str(e.get("name", "")),
            factor=float(e["factor"]),
            reason=str(e.get("reason", "")),
        )
        for e in outcome.context_rules
    ]


def triggered_out(outcome: ScoreOutcome) -> list[TriggeredRuleOut]:
    return [TriggeredRuleOut(**d) for d in outcome.rule.triggered_details]


def suppressed_out(outcome: ScoreOutcome) -> list[SuppressedRuleOut]:
    return [SuppressedRuleOut(**d) for d in outcome.rule.suppressed_rules]


def to_score_response(outcome: ScoreOutcome, duplicate: bool, latency_ms: float) -> ScoreResponse:
    """/score body."""
    rule = outcome.rule
    return ScoreResponse(
        transaction_id=outcome.transaction_id,
        anomaly_score=outcome.anomaly_score,
        raw_anomaly_score=outcome.raw_anomaly_score,
        layer_scores=outcome.layer_scores,
        adjusted_score=outcome.adjusted_score,
        context_rules=_context(outcome),
        final_score=rule.final_score,
        final_decision=rule.final_decision,  # type: ignore[arg-type]
        decision_source=rule.decision_source,
        triggered_rules=triggered_out(outcome),
        suppressed_rules=suppressed_out(outcome),
        reasons=rule.reasons,
        warnings=outcome.warnings,
        duplicate=duplicate,
        state_updated=not duplicate,
        latency_ms=latency_ms,
    )


def render_summary(facts: Facts) -> str:
    """Template explanation (Turkish) built only from the facts."""
    parts = [
        f"Karar: {facts.decision} (kaynak: {facts.decision_source}, "
        f"nihai skor {facts.final_score:.3f}).",
        "Karar nedeni: " + (" ".join(facts.reasons) or "kayıtlı gerekçe yok."),
    ]
    top = sorted(facts.layer_scores.items(), key=lambda kv: kv[1], reverse=True)[:TOP_LAYERS]
    if top:
        parts.append(
            "En yüksek katman skorları: " + ", ".join(f"{n} {v:.2f}" for n, v in top) + "."
        )
    if facts.context_rules:
        parts.append(
            "Uygulanan context kuralları: "
            + ", ".join(f"{c.id} (x{c.factor:.2f})" for c in facts.context_rules)
            + "."
        )
    if facts.thresholds.score_review is not None:
        parts.append(f"Skor inceleme eşiği: {facts.thresholds.score_review:.3f}.")
    return " ".join(parts)


def to_facts(outcome: ScoreOutcome, thresholds: dict[str, float | None]) -> Facts:
    """Deterministic facts of /explain."""
    rule = outcome.rule
    facts = Facts(
        decision=rule.final_decision,
        decision_source=rule.decision_source,
        final_score=rule.final_score,
        anomaly_score=outcome.anomaly_score,
        adjusted_score=outcome.adjusted_score,
        layer_scores=outcome.layer_scores,
        thresholds=Thresholds(**thresholds),  # type: ignore[arg-type]
        context_rules=_context(outcome),
        triggered_rules=triggered_out(outcome),
        suppressed_rules=suppressed_out(outcome),
        reasons=rule.reasons,
        summary="",
        warnings=outcome.warnings,
    )
    facts.summary = render_summary(facts)
    return facts


def classify_llm(response: AgentResponse | None, error: str | None = None) -> LlmStatus:
    """llm_status of /explain from the agent response.

    ok: a RAG narrative exists. timeout/unavailable/error: the explainer step failed.
    unavailable also covers a template fallback caused by a missing LLM; empty: the LLM answered
    with nothing usable.
    """
    if response is None:
        return "error"
    explanation = response.explanation
    if explanation is None:
        text = " ".join([*response.errors, error or ""]).lower()
        if "no answer within" in text:
            return "timeout"
        if any(k in text for k in ("unavailable", "unreachable", "connect", "ollama", "embedding")):
            return "unavailable"
        return "error"
    if explanation.origin == "template":
        return "unavailable" if "llm_unavailable" in explanation.flags else "empty"
    return "ok"


def to_narrative(response: AgentResponse | None) -> Narrative | None:
    """The RAG text of the agent run, or None (no text, or only the template)."""
    explanation = response.explanation if response else None
    if explanation is None or explanation.origin != "rag" or not explanation.text:
        return None
    return Narrative(
        label=explanation.label,
        text=explanation.text,
        grounded=explanation.grounded,
        abstained=explanation.abstained,
        sources=explanation.sources,
        warning=explanation.warning,
    )


def to_agent_info(response: AgentResponse | None) -> AgentInfo:
    """Short summary of the agent run (the full trace is a separate field)."""
    if response is None:
        return AgentInfo()
    return AgentInfo(
        status=response.status,
        plan=response.plan.steps,
        plan_source=response.plan.source,
        errors=response.errors,
        total_ms=response.total_ms,
    )


def trace_dicts(response: AgentResponse | None) -> list[dict[str, Any]]:
    """Trace entries as JSON-friendly dicts."""
    if response is None:
        return []
    return [t.model_dump(mode="json") for t in response.trace]
