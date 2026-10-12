"""FeatureAgent: a raw transaction is featurized by delegation (K-54), all mocked."""

from __future__ import annotations

from src.agents.messages import AnalystRequest
from tests.agents.conftest import RECORD, FakeRecords, plan_json


def _pairs(response) -> list[tuple[str, str, str]]:
    return [(t.sender, t.recipient, t.intent) for t in response.trace if t.recipient != "-"]


def test_anomaly_agent_asks_the_feature_agent_for_a_raw_transaction(make_system) -> None:
    records = FakeRecords()
    system = make_system(records=records)
    response = system.coordinator.analyze(AnalystRequest(transaction=dict(RECORD)))
    assert _pairs(response) == [
        ("client", "coordinator", "analyze"),
        ("coordinator", "anomaly", "score"),
        ("anomaly", "feature", "featurize"),
        ("coordinator", "context", "adjust"),
        ("coordinator", "rule", "evaluate"),
        ("coordinator", "explainer", "explain"),
    ]
    by_id = {t.message_id: t for t in response.trace}
    assert by_id[response.trace[2].parent_id].recipient == "anomaly"
    assert response.status == "ok" and response.transaction_id == 42
    # featurized once; the built record reaches the later steps (not the raw transaction)
    assert records.calls == [RECORD]
    assert system.adjuster.last_record["ent_txn_count"] == 7
    assert system.engine.calls[0]["record"]["ent_txn_count"] == 7


def test_full_delegation_chain_down_to_the_feature_agent(make_system) -> None:
    records = FakeRecords()
    system = make_system(records=records)
    system.llm.answer = plan_json("rule:evaluate", "explainer:explain")
    response = system.coordinator.analyze(
        AnalystRequest(transaction=dict(RECORD), question="sadece karar")
    )
    assert response.plan.source == "llm"
    assert _pairs(response)[:5] == [
        ("client", "coordinator", "analyze"),
        ("coordinator", "rule", "evaluate"),
        ("rule", "context", "adjust"),
        ("context", "anomaly", "score"),
        ("anomaly", "feature", "featurize"),
    ]
    chain = [t.recipient for t in response.trace[1:5]]
    by_id = {t.message_id: t for t in response.trace}
    parents = [by_id[t.parent_id].recipient for t in response.trace[2:5]]
    assert parents == chain[:-1]  # every hop was sent while handling the previous one
    assert response.decision == "review" and len(records.calls) == 1
    assert system.engine.calls[0]["record"]["ent_txn_count"] == 7


def test_a_ready_record_is_not_featurized_again(make_system) -> None:
    records = FakeRecords()
    system = make_system(records=records)
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert ("anomaly", "feature", "featurize") not in _pairs(response)
    assert records.calls == []


def test_without_a_record_source_there_is_no_feature_agent(make_system) -> None:
    system = make_system()
    assert "feature" not in system.bus.agents
    response = system.coordinator.analyze(AnalystRequest(transaction=dict(RECORD)))
    assert response.status == "error" and response.decision is None  # nothing is invented
