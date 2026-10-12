"""Hard deadline for a blocking call (LLM/RAG) without extra dependencies."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from src.agents.errors import AgentTimeout


def call_with_timeout(fn: Callable[[], Any], seconds: float) -> Any:
    """Run fn() in a daemon thread and wait at most `seconds`.

    Raises AgentTimeout on expiry (the thread is abandoned; the HTTP client timeouts configured
    in configs/rag.yaml end it later) or re-raises the exception fn raised.
    """
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AgentTimeout(f"no answer within {seconds:g}s")
    if "error" in box:
        raise box["error"]
    return box["value"]
