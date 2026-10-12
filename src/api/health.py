"""Health checks: are the model artifacts loaded, is the FAISS index there, does Ollama answer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from src.api.config import ApiSettings
from src.api.schemas import ComponentHealth, HealthResponse
from src.rag.config import RagSettings

logger = logging.getLogger(__name__)

INDEX_FILES = ("index.faiss", "chunks.jsonl")


class HealthService:
    """Reports the state of the three dependencies. It never raises.

    status: ok = all ready; degraded = models are loaded (so /score works) but the index or Ollama
    is not; down = the model artifacts could not be loaded.
    """

    def __init__(
        self,
        load_models: Callable[[], Any],
        rag_settings: RagSettings,
        api_settings: ApiSettings,
        http_client: httpx.Client,
    ) -> None:
        self._load_models = load_models
        self.rag_settings = rag_settings
        self.api_settings = api_settings
        self.http = http_client

    def models(self) -> ComponentHealth:
        """Feature pipeline, anomaly layers, context engine and rule engine (OnlineScorer)."""
        try:
            scorer = self._load_models()
            return ComponentHealth(ok=True, detail=scorer.state_summary())
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            logger.warning("model artifacts not loaded: %s", exc)
            return ComponentHealth(ok=False, detail={"error": f"{type(exc).__name__}: {exc}"})

    def index(self) -> ComponentHealth:
        """FAISS index and chunk metadata files (built by `make rag-index`)."""
        directory = self.rag_settings.index_dir
        missing = [f for f in INDEX_FILES if not (directory / f).exists()]
        detail: dict[str, Any] = {"path": str(directory), "missing": missing}
        return ComponentHealth(ok=not missing, detail=detail)

    def ollama(self) -> ComponentHealth:
        """Ollama reachable, and the configured chat and embedding models installed."""
        host = self.rag_settings.llm.host.rstrip("/")
        needed = [self.rag_settings.llm.model, self.rag_settings.embedding.model]
        try:
            response = self.http.get(
                f"{host}/api/tags", timeout=self.api_settings.health.ollama_timeout_seconds
            )
            response.raise_for_status()
            installed = [m.get("name", "") for m in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return ComponentHealth(ok=False, detail={"host": host, "error": type(exc).__name__})
        present = {m: any(n == m or n.startswith(f"{m}:") for n in installed) for m in needed}
        return ComponentHealth(ok=all(present.values()), detail={"host": host, "models": present})

    def check(self) -> HealthResponse:
        """Run all three checks."""
        models, index, ollama = self.models(), self.index(), self.ollama()
        if not models.ok:
            status = "down"
        elif index.ok and ollama.ok:
            status = "ok"
        else:
            status = "degraded"
        return HealthResponse(
            status=status, model_artifacts=models, faiss_index=index, ollama=ollama
        )
