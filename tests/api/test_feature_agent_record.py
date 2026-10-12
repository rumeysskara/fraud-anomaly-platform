"""FeatureAgent returns exactly OnlineScorer.build_record; /explain shows the delegation (K-54)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from src.agents.bus import MessageBus
from src.agents.feature_agent import FeatureAgent
from src.agents.messages import FEATURE, INTENT_FEATURIZE, BusMessage
from tests.api.conftest import PAYLOAD, World


def _featurize(world: World, txn: dict[str, Any]) -> dict[str, Any]:
    agent = FeatureAgent(MessageBus(), lambda: world.scorer)
    message = BusMessage(
        sender="anomaly", recipient=FEATURE, intent=INTENT_FEATURIZE, payload={"transaction": txn}
    )
    reply = agent.handle(message)
    assert reply.status == "ok"
    return reply.payload["record"]


def test_feature_agent_record_equals_build_record(world: World) -> None:
    txn = dict(PAYLOAD)
    assert _featurize(world, txn) == world.scorer.build_record(txn)
    assert world.pipeline.store.updates == []  # read-only


def test_after_score_the_feature_agent_returns_the_recorded_features(world: World) -> None:
    txn = dict(PAYLOAD)
    before = world.scorer.build_record(txn)
    world.scorer.score(txn)  # appends txn to the history
    assert _featurize(world, txn) == before == world.scorer.analyze(txn)[0]


def test_explain_trace_shows_anomaly_delegating_to_feature(client: TestClient) -> None:
    data = client.post("/explain", json={"transaction": dict(PAYLOAD)}).json()
    hops = [(t["sender"], t["recipient"], t["intent"]) for t in data["trace"]]
    assert hops[:3] == [
        ("client", "coordinator", "analyze"),
        ("coordinator", "anomaly", "score"),
        ("anomaly", "feature", "featurize"),
    ]
    assert data["agent"]["status"] == "ok" and data["facts"]["decision"] == "allow"
