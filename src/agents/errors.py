"""Agent-layer exceptions."""

from __future__ import annotations


class AgentError(Exception):
    """A delegated task came back with status=error (or the agent failed itself)."""


class AgentSkipped(Exception):
    """Raised by a handler that deliberately does nothing; the bus replies status=skipped."""


class AgentTimeout(AgentError):
    """A call exceeded its configured deadline."""
