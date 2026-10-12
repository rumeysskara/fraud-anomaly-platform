"""Shared base for runtime agents: intent dispatch and delegation through the bus."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from src.agents.bus import MessageBus
from src.agents.errors import AgentError
from src.agents.messages import BusMessage
from src.core.interfaces import BaseAgent

Handler = Callable[[BusMessage], BaseModel]


class Agent(BaseAgent):
    """An agent has a name, a bus and one handler per intent.

    Handlers return a pydantic reply payload. Errors raised by a handler become a reply with
    status=error (the bus does that), so subclasses contain no try/except for control flow.
    """

    def __init__(self, name: str, bus: MessageBus) -> None:
        self.name = name
        self.bus = bus
        self._handlers: dict[str, Handler] = {}

    def on(self, intent: str, handler: Handler) -> None:
        """Register the handler of an intent."""
        self._handlers[intent] = handler

    @property
    def intents(self) -> list[str]:
        """Intents this agent accepts."""
        return list(self._handlers)

    def handle(self, message: BusMessage) -> BusMessage:  # type: ignore[override]
        """Dispatch by intent; an unknown intent is an error reply."""
        handler = self._handlers.get(message.intent)
        if handler is None:
            return message.reply(
                {"error": f"{self.name} has no intent '{message.intent}'"}, "error"
            )
        return message.reply(handler(message).model_dump())

    def delegate(
        self, recipient: str, intent: str, payload: BaseModel, parent: BusMessage
    ) -> dict[str, Any]:
        """Ask another agent through the bus; return its reply payload or raise AgentError."""
        message = BusMessage(
            sender=self.name,
            recipient=recipient,
            intent=intent,
            correlation_id=parent.correlation_id,
            parent_id=parent.message_id,
            payload=payload.model_dump(),
            depth=parent.depth + 1,
        )
        reply = self.bus.send(message)
        if reply.status != "ok":
            detail = reply.payload.get("error") or reply.payload.get("reason") or reply.status
            raise AgentError(f"{recipient}.{intent} failed: {detail}")
        return reply.payload
