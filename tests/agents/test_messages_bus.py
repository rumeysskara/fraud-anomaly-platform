"""Message schema and the bus (mediator): replies, errors, depth limit, trace."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.errors import AgentSkipped
from src.agents.messages import BusMessage, ScoreRequest
from src.core.interfaces import BaseAgent
from src.core.types import AgentMessage


def test_message_schema_has_required_fields() -> None:
    msg = BusMessage(sender="a", recipient="b", intent="score", payload={"x": 1})
    assert isinstance(msg, AgentMessage)  # extends the shared type
    assert msg.message_id and msg.correlation_id and msg.timestamp
    assert msg.status == "ok" and msg.parent_id is None
    dumped = msg.model_dump()
    for field in (
        "message_id",
        "correlation_id",
        "sender",
        "recipient",
        "intent",
        "payload",
        "timestamp",
        "status",
    ):
        assert field in dumped


def test_status_is_restricted_and_ids_unique() -> None:
    with pytest.raises(ValidationError):
        BusMessage(sender="a", recipient="b", intent="x", status="weird")  # type: ignore[arg-type]
    a = BusMessage(sender="a", recipient="b", intent="x")
    b = BusMessage(sender="a", recipient="b", intent="x")
    assert a.message_id != b.message_id


def test_reply_swaps_parties_and_keeps_correlation() -> None:
    msg = BusMessage(sender="a", recipient="b", intent="score")
    reply = msg.reply({"ok": 1})
    assert (reply.sender, reply.recipient) == ("b", "a")
    assert reply.correlation_id == msg.correlation_id and reply.parent_id == msg.message_id


def test_payload_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate({"record": {}, "decision": "allow"})


class Echo(Agent):
    def __init__(self, bus: MessageBus, name: str = "echo") -> None:
        super().__init__(name, bus)
        self.on("ping", lambda m: ScoreRequest(record=m.payload))
        self.on("boom", self._boom)
        self.on("skip", self._skip)
        self.on("loop", self._loop)

    def _boom(self, m: BusMessage):
        raise RuntimeError("kaput")

    def _skip(self, m: BusMessage):
        raise AgentSkipped("nothing to do")

    def _loop(self, m: BusMessage):
        return ScoreRequest(record=self.delegate(self.name, "loop", ScoreRequest(record={}), m))


def test_bus_delivers_and_traces() -> None:
    bus = MessageBus()
    bus.register(Echo(bus))
    msg = BusMessage(sender="client", recipient="echo", intent="ping", payload={"a": 1})
    reply = bus.send(msg)
    assert reply.status == "ok"
    trace = bus.pop_trace(msg.correlation_id)
    assert len(trace) == 1
    entry = trace[0]
    assert (entry.sender, entry.recipient, entry.intent, entry.status) == (
        "client",
        "echo",
        "ping",
        "ok",
    )
    assert entry.duration_ms >= 0 and entry.payload_keys == ["a"]
    assert bus.pop_trace(msg.correlation_id) == []  # forgotten after pop


def test_failures_become_error_replies_not_exceptions() -> None:
    bus = MessageBus()
    bus.register(Echo(bus))
    err = bus.send(BusMessage(sender="c", recipient="echo", intent="boom"))
    assert err.status == "error" and "kaput" in err.payload["error"]
    unknown = bus.send(BusMessage(sender="c", recipient="nobody", intent="x"))
    assert unknown.status == "error"
    bad_intent = bus.send(BusMessage(sender="c", recipient="echo", intent="nope"))
    assert bad_intent.status == "error"
    skipped = bus.send(BusMessage(sender="c", recipient="echo", intent="skip"))
    assert skipped.status == "skipped"


def test_delegation_depth_is_limited() -> None:
    bus = MessageBus(max_depth=3)
    bus.register(Echo(bus))
    msg = BusMessage(sender="c", recipient="echo", intent="loop")
    reply = bus.send(msg)
    assert reply.status == "error"
    trace = bus.pop_trace(msg.correlation_id)
    assert len(trace) == 5 and trace[-1].status == "error"  # depth 0..4 then refused


def test_agents_register_by_name_only() -> None:
    bus = MessageBus()
    agent: BaseAgent = Echo(bus, "e1")
    bus.register(agent)
    assert bus.agents == ["e1"]
