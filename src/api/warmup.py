"""Background warm-up of the Ollama models at API startup (decision K-50).

The first /explain after a start used to spend most of its 50 s explainer budget loading
qwen2.5:7b and bge-m3 into memory. At startup one short embedding call and one short chat call
are sent in a daemon thread, so startup is not blocked; together with `keep_alive` in
configs/rag.yaml the models then stay loaded. /health shows the state of each model.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Literal

from src.api.config import ApiSettings
from src.core.interfaces import Embedder, LLMClient

logger = logging.getLogger(__name__)

WarmState = Literal["disabled", "not_started", "running", "ok", "error"]


class ModelWarmer:
    """Sends one embedding and one chat request in a background thread and records the result.

    Failures (Ollama down, model missing) are only recorded; the API keeps working and the
    first real request simply pays the load time.
    """

    def __init__(self, embedder: Embedder, llm: LLMClient, settings: ApiSettings) -> None:
        self.embedder = embedder
        self.llm = llm
        self.settings = settings.warmup
        initial: WarmState = "not_started" if self.settings.enabled else "disabled"
        self._state: dict[str, dict[str, Any]] = {
            "embedding": {"status": initial},
            "llm": {"status": initial},
        }
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the warm-up thread once (no-op when disabled or already started)."""
        if not self.settings.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self.run, name="model-warmup", daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the warm-up thread (used by tests and scripts)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def run(self) -> None:
        """Warm the embedding model, then the LLM (sequential: Ollama loads one at a time)."""
        self._warm("embedding", lambda: self.embedder.embed([self.settings.embedding_text]))
        self._warm("llm", lambda: self.llm.generate(self.settings.llm_prompt))

    def state(self) -> dict[str, dict[str, Any]]:
        """Copy of the per-model state: status, duration_ms, error."""
        with self._lock:
            return {name: dict(entry) for name, entry in self._state.items()}

    def ready(self) -> bool:
        """True when both models answered the warm-up request."""
        return all(entry["status"] == "ok" for entry in self.state().values())

    def _warm(self, name: str, call: Any) -> None:
        self._set(name, status="running")
        started = time.perf_counter()
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - recorded and shown by /health
            logger.warning("warm-up of %s failed: %s", name, exc)
            self._set(name, status="error", error=f"{type(exc).__name__}: {exc}")
            return
        duration = round((time.perf_counter() - started) * 1000, 1)
        logger.info("warm-up of %s done in %.0f ms", name, duration)
        self._set(name, status="ok", duration_ms=duration)

    def _set(self, name: str, **values: Any) -> None:
        with self._lock:
            self._state[name] = values
