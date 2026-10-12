"""Delegation chain, trace content and resilience of the full agent flow (all mocked)."""

from __future__ import annotations

from src.agents.messages import AnalystRequest
from tests.agents.conftest import RECORD, FakeEngine, FakeRAG, FakeScoring, plan_json


def _pairs(response) -> list[tuple[str, str, str]]:
    return [(t.sender, t.recipient, t.intent) for t in response.trace if t.recipient != "-"]


def test_default_plan_runs_four_agents_in_order(make_system) -> None:
    system = make_system()
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.plan.source == "default"
    assert _pairs(response) == [
        ("client", "coordinator", "analyze"),
        ("coordinator", "anomaly", "score"),
        ("coordinator", "context", "adjust"),
        ("coordinator", "rule", "evaluate"),
        ("coordinator", "explainer", "explain"),
    ]
    assert response.status == "ok" and response.decision == "review"
    assert response.anomaly_score == 0.7 and response.context_rules == ["C3"]
    assert response.triggered_rules == ["R01"]
    # scores were passed on, not recomputed through delegation
    assert system.scoring.calls == 1 and system.adjuster.calls == 1
    # the rule engine got the Step 6 unclipped score and the layer scores reached the context step
    assert system.engine.calls[0]["score"] == 0.55
    assert system.adjuster.last_record["temporal_score"] == 0.9


def test_trace_entries_have_who_what_how_long(make_system) -> None:
    response = make_system().coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert [t.seq for t in response.trace] == [1, 2, 3, 4, 5]
    for entry in response.trace:
        assert entry.sender and entry.recipient and entry.intent
        assert entry.status == "ok" and entry.duration_ms >= 0 and entry.message_id
    # records are large: the trace keeps payload keys only
    assert "record" in response.trace[1].payload_keys


def test_rule_agent_delegates_to_context_and_anomaly(make_system) -> None:
    system = make_system(llm=None)
    # K-51: a question plan must contain the explainer; anomaly/context may still be left out.
    system.llm.answer = plan_json("rule:evaluate", "explainer:explain")
    response = system.coordinator.analyze(
        AnalystRequest(record=dict(RECORD), question="sadece karar")
    )
    assert response.plan.source == "llm"
    assert response.plan.steps == ["rule:evaluate", "explainer:explain"]
    assert _pairs(response)[:4] == [
        ("client", "coordinator", "analyze"),
        ("coordinator", "rule", "evaluate"),
        ("rule", "context", "adjust"),
        ("context", "anomaly", "score"),
    ]
    assert ("coordinator", "explainer", "explain") in _pairs(response)
    by_id = {t.message_id: t for t in response.trace}
    anomaly = response.trace[3]
    assert by_id[anomaly.parent_id].recipient == "context"  # parent links form the chain
    assert response.decision == "review" and response.explanation is not None
    assert response.anomaly_score == 0.7 and response.context_rules == ["C3"]
    assert system.scoring.calls == 1


def test_explainer_gets_rule_ids_from_rule_result(make_system) -> None:
    system = make_system(engine=FakeEngine("block", ["R05", "R09"]))
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert system.rag.calls[0]["rule_ids"] == ["R05", "R09"]
    assert response.explanation is not None
    assert response.explanation.label == "destek bilgisi"
    assert response.explanation.affects_decision is False


def test_rule_agent_does_not_write_cooldown_state(make_system) -> None:
    system = make_system()
    system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert system.engine.calls[0]["update_state"] is False  # K-35


def test_explainer_failure_keeps_the_decision(make_system) -> None:
    ok = make_system().coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    system = make_system(rag=FakeRAG(fail=True))
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.explanation is None
    assert response.status == "degraded" and response.errors
    assert response.decision == ok.decision and response.final_score == ok.final_score
    explain = [t for t in response.trace if t.recipient == "explainer"][0]
    assert explain.status == "error" and "rag down" in (explain.detail or "")


def test_explainer_timeout_keeps_the_decision(make_system, settings) -> None:
    fast = settings.model_copy(
        update={"explainer": settings.explainer.model_copy(update={"timeout_seconds": 0.05})}
    )
    system = make_system(rag=FakeRAG(delay=0.5), cfg=fast)
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.explanation is None and response.decision == "review"
    assert [t for t in response.trace if t.recipient == "explainer"][0].status == "error"


def test_scoring_failure_does_not_crash_and_invents_no_decision(make_system) -> None:
    system = make_system(scoring=FakeScoring(fail=True))
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.status == "error" and response.decision is None
    assert response.errors and any(t.status == "error" for t in response.trace)


def test_rule_failure_is_reported(make_system) -> None:
    class Broken(FakeEngine):
        def evaluate(self, record, anomaly_score, update_state=True):  # type: ignore[override]
            raise KeyError("record is missing rule inputs")

    response = make_system(engine=Broken()).coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.status == "error" and response.decision is None
    assert response.explanation is None  # nothing to explain without a rule result
