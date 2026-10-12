"""MessageBus: the Mediator. Agents never call each other; every call goes through send()."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from src.agents.errors import AgentSkipped
from src.agents.messages import BusMessage, TraceEntry
from src.core.interfaces import BaseAgent

logger = logging.getLogger(__name__)


class MessageBus:
    """Synchronous in-process mediator with a per-request trace.

    send() delivers a message to the registered recipient and returns its reply. A failing agent
    never raises through the bus: the caller gets a reply with status=error. Every call is
    recorded as a TraceEntry under the message's correlation id.
    """

    def __init__(self, max_depth: int = 6) -> None:
        self.max_depth = max_depth
        self._agents: dict[str, BaseAgent] = {}
        self._traces: dict[str, list[TraceEntry]] = {}
        self._lock = threading.Lock()

    def register(self, agent: BaseAgent) -> None:
        """Make an agent reachable under its name."""
        self._agents[agent.name] = agent

    @property
    def agents(self) -> list[str]:
        """Registered agent names."""
        return list(self._agents)

    def send(self, message: BusMessage) -> BusMessage:
        """Deliver `message`; always return a reply (status ok / error / skipped)."""
        entry = self._open(message)
        started = time.perf_counter()
        agent = self._agents.get(message.recipient)
        if agent is None:
            reply = message.reply({"error": f"unknown recipient '{message.recipient}'"}, "error")
        elif message.depth > self.max_depth:
            reply = message.reply({"error": f"delegation depth > {self.max_depth}"}, "error")
        else:
            try:
                reply = agent.handle(message)  # type: ignore[assignment]
            except AgentSkipped as exc:
                reply = message.reply({"reason": str(exc)}, "skipped")
            except Exception as exc:  # noqa: BLE001 - one failing agent must not crash the request
                logger.warning("agent %s failed on %s: %s", message.recipient, message.intent, exc)
                reply = message.reply({"error": f"{type(exc).__name__}: {exc}"}, "error")
        entry.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        entry.status = reply.status
        if reply.status != "ok":
            entry.detail = str(reply.payload.get("error") or reply.payload.get("reason") or "")
        return reply

    def note(self, correlation_id: str, sender: str, event: str, detail: str = "") -> None:
        """Record a non-message event (e.g. plan_fallback) in the trace."""
        self._append(
            correlation_id,
            TraceEntry(
                seq=0,
                message_id="",
                sender=sender,
                recipient="-",
                intent=event,
                status="skipped",
                timestamp=datetime.now(UTC),
                detail=detail or None,
            ),
        )

    def pop_trace(self, correlation_id: str) -> list[TraceEntry]:
        """Return the trace of a request (ordered by start) and forget it."""
        with self._lock:
            return self._traces.pop(correlation_id, [])

    def _open(self, message: BusMessage) -> TraceEntry:
        entry = TraceEntry(
            seq=0,
            message_id=message.message_id,
            parent_id=message.parent_id,
            sender=message.sender,
            recipient=message.recipient,
            intent=message.intent,
            status="pending",
            timestamp=message.timestamp,
            payload_keys=sorted(message.payload),
        )
        self._append(message.correlation_id, entry)
        return entry

    def _append(self, correlation_id: str, entry: TraceEntry) -> None:
        with self._lock:
            entries = self._traces.setdefault(correlation_id, [])
            entry.seq = len(entries) + 1
            entries.append(entry)
