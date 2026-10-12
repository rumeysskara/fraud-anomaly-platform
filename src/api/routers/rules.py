"""Rule endpoints: GET /rules, POST /rules/reload, POST /rules/evaluate."""

from __future__ import annotations

import time

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.api.mappers import suppressed_out, triggered_out
from src.api.online import OnlineScorer
from src.api.schemas import (
    RuleOut,
    RulesEvaluateRequest,
    RulesEvaluateResponse,
    RulesListResponse,
    RulesReloadResponse,
)
from src.container import Container
from src.rules.engine import RuleEngine
from src.rules.schema import Rule

router = APIRouter(tags=["rules"])


def _rule_out(rule: Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        priority=rule.priority,
        severity=rule.severity,
        enabled=rule.enabled,
        decision=rule.action.decision,
        risk_boost=rule.action.risk_boost,
        flag=rule.action.flag,
        cooldown_seconds=rule.cooldown.window_seconds if rule.cooldown else None,
        tags=rule.tags,
    )


@router.get("/rules", response_model=RulesListResponse, summary="Loaded rules")
@inject
def list_rules(
    engine: RuleEngine = Depends(Provide[Container.rule_engine]),  # noqa: B008
) -> RulesListResponse:
    """The rule set currently loaded from configs/rules.yaml and rules_extra.json."""
    rules = engine.repository.rules
    return RulesListResponse(
        count=len(rules),
        enabled_count=sum(r.enabled for r in rules),
        rules=[_rule_out(r) for r in rules],
    )


@router.post("/rules/reload", response_model=RulesReloadResponse, summary="Re-read the rule files")
@inject
def reload_rules(
    engine: RuleEngine = Depends(Provide[Container.rule_engine]),  # noqa: B008
) -> RulesReloadResponse:
    """Re-reads rule files and learned thresholds; an invalid file is rejected with 422 and the
    previous rule set stays active."""
    rules = engine.reload()
    return RulesReloadResponse(
        count=len(rules),
        enabled_count=sum(r.enabled for r in rules),
        rule_ids=[r.id for r in rules],
    )


@router.post(
    "/rules/evaluate",
    response_model=RulesEvaluateResponse,
    summary="Evaluate a transaction with the loaded or a request-supplied rule set",
)
@inject
def evaluate_rules(
    body: RulesEvaluateRequest,
    scorer: OnlineScorer = Depends(Provide[Container.online_scorer]),  # noqa: B008
) -> RulesEvaluateResponse:
    """A `rules` list in the body is validated with the rule schema (422 when invalid) and used
    for this request only. The cooldown state is read, never written."""
    started = time.perf_counter()
    rules = None if body.rules is None else scorer.parse_rules(body.rules)  # 422 when invalid
    _, outcome = scorer.analyze(body.transaction.model_dump(), rules=rules)  # type: ignore[attr-defined]
    rule = outcome.rule
    return RulesEvaluateResponse(
        transaction_id=outcome.transaction_id,
        rule_set="loaded" if rules is None else "request",
        final_decision=rule.final_decision,
        decision_source=rule.decision_source,
        final_score=rule.final_score,
        anomaly_score=outcome.anomaly_score,
        adjusted_score=outcome.adjusted_score,
        triggered_rules=triggered_out(outcome),
        suppressed_rules=suppressed_out(outcome),
        applied_rules=rule.applied_rules,
        reasons=rule.reasons,
        flags=rule.flags,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )
