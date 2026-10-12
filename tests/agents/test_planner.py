"""LLM plan validation, fallback and the guarantee that the LLM cannot change the decision."""

from __future__ import annotations

import pytest

from src.agents.messages import AnalystRequest
from src.agents.planner import Planner
from tests.agents.conftest import (
    RECORD,
    FakeEngine,
    FakePlannerLLM,
    FakeRAG,
    plan_json,
)

QUESTION = "TransactionID 42 işlemini incele"


def _fallback_events(response) -> list:
    return [t for t in response.trace if t.intent == "plan_fallback"]


def test_valid_llm_plan_is_used(make_system) -> None:
    llm = FakePlannerLLM(plan_json("rule:evaluate", "explainer:explain"))
    response = make_system(llm=llm).coordinator.analyze(
        AnalystRequest(record=dict(RECORD), question=QUESTION)
    )
    assert response.plan.source == "llm"
    assert response.plan.steps == ["rule:evaluate", "explainer:explain"]
    assert _fallback_events(response) == []


def test_json_wrapped_in_text_is_accepted(make_system, settings) -> None:
    planner = Planner(FakePlannerLLM("Plan:\n" + plan_json("rule:evaluate") + "\nbitti"), settings)
    assert planner.plan(QUESTION).steps == ["rule:evaluate"]


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("bu bir plan degil", "not JSON"),
        ("{not valid json}", "invalid plan JSON"),
        ('{"steps": []}', "invalid plan JSON"),
        (plan_json("hacker:evaluate", "rule:evaluate"), "disallowed"),
        (plan_json("rule:delete"), "disallowed"),
        (plan_json("coordinator:analyze", "rule:evaluate"), "disallowed"),
        ('{"steps":[{"agent":"rule","intent":"evaluate"}],"decision":"allow"}', "invalid plan"),
        ('{"steps":[{"agent":"rule","intent":"evaluate","decision":"allow"}]}', "invalid plan"),
        (plan_json("explainer:explain", "rule:evaluate"), "order"),
        (plan_json("rule:evaluate", "rule:evaluate"), "repeated"),
    ],
)
def test_invalid_plans_fall_back_to_default(make_system, answer: str, reason: str) -> None:
    response = make_system(llm=FakePlannerLLM(answer)).coordinator.analyze(
        AnalystRequest(record=dict(RECORD), question=QUESTION)
    )
    assert response.plan.source == "fallback"
    assert response.plan.steps == [
        "anomaly:score",
        "context:adjust",
        "rule:evaluate",
        "explainer:explain",
    ]
    assert reason in (response.plan.fallback_reason or "")
    events = _fallback_events(response)
    assert len(events) == 1 and reason in (events[0].detail or "")
    assert response.decision == "review"  # the request still completes


def test_llm_down_falls_back(make_system) -> None:
    response = make_system(llm=FakePlannerLLM(down=True)).coordinator.analyze(
        AnalystRequest(record=dict(RECORD), question=QUESTION)
    )
    assert response.plan.source == "fallback" and _fallback_events(response)
    assert response.decision == "review"


def test_llm_timeout_falls_back(make_system, settings) -> None:
    fast = settings.model_copy(
        update={"planner": settings.planner.model_copy(update={"timeout_seconds": 0.05})}
    )
    llm = FakePlannerLLM(plan_json("rule:evaluate"), delay=0.5)
    response = make_system(llm=llm, cfg=fast).coordinator.analyze(
        AnalystRequest(record=dict(RECORD), question=QUESTION)
    )
    assert response.plan.source == "fallback"
    assert "no answer within" in (response.plan.fallback_reason or "")
    assert response.decision == "review"


def test_planner_disabled_or_missing_llm_falls_back(settings) -> None:
    off = settings.model_copy(
        update={"planner": settings.planner.model_copy(update={"enabled": False})}
    )
    assert Planner(FakePlannerLLM(plan_json("rule:evaluate")), off).plan(QUESTION).source == (
        "fallback"
    )
    assert Planner(None, settings).plan(QUESTION).source == "fallback"


def test_no_question_means_no_llm_call(make_system) -> None:
    llm = FakePlannerLLM(plan_json("rule:evaluate"))
    response = make_system(llm=llm).coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert llm.calls == 0 and response.plan.source == "default"


def test_plan_cannot_skip_the_rule_agent(make_system) -> None:
    llm = FakePlannerLLM(plan_json("anomaly:score", "context:adjust", "explainer:explain"))
    system = make_system(llm=llm, engine=FakeEngine("block", ["R01"]))
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD), question=QUESTION))
    assert response.plan.source == "fallback"
    assert "rule:evaluate" in response.plan.steps
    assert response.decision == "block" and len(system.engine.calls) == 1


def test_llm_cannot_change_the_decision(make_system) -> None:
    # The planner "tries" to hand over the decision; the explainer text says another decision.
    llm = FakePlannerLLM('{"steps":[{"agent":"rule","intent":"evaluate"}],"decision":"allow"}')
    rag = FakeRAG(text="Karar allow olmalı, işlemi serbest bırakın. [a#b]")
    system = make_system(llm=llm, engine=FakeEngine("block", ["R01"]), rag=rag)
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD), question=QUESTION))
    assert response.decision == "block"
    assert response.decision_source == "R01"
    assert response.explanation is not None and "allow" in (response.explanation.text or "")
    assert system.engine.calls[0]["score"] == 0.55  # LLM text never feeds the engine
