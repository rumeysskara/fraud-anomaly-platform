"""Ollama embedding client (bge-m3). The HTTP client is injectable so tests can mock it."""

from __future__ import annotations

import logging

import httpx
import numpy as np

from src.core.interfaces import Embedder
from src.rag.config import EmbeddingConfig
from src.rag.errors import EmbeddingUnavailableError

logger = logging.getLogger(__name__)


class OllamaEmbedder(Embedder):
    """Embeds texts with a local Ollama model through POST /api/embed."""

    def __init__(self, config: EmbeddingConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(base_url=config.host, timeout=config.timeout_seconds)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return float32 vectors of shape (len(texts), dim); raises EmbeddingUnavailableError."""
        if not texts:
            return np.zeros((0, 0), dtype="float32")
        batches = []
        size = self.config.batch_size
        for start in range(0, len(texts), size):
            batches.append(self._embed_batch(texts[start : start + size]))
        return np.vstack(batches).astype("float32")

    def _embed_batch(self, texts: list[str]) -> np.ndarray:
        payload = {"model": self.config.model, "input": texts}
        try:
            response = self._client.post("/api/embed", json=payload)
        except httpx.HTTPError as exc:  # connection refused, timeout, ...
            raise EmbeddingUnavailableError(
                f"Ollama embedding endpoint unreachable ({self.config.host}): {exc}"
            ) from exc
        if response.status_code == 404:
            raise EmbeddingUnavailableError(
                f"Embedding model '{self.config.model}' is not installed "
                f"(run: ollama pull {self.config.model})"
            )
        if response.status_code != 200:
            raise EmbeddingUnavailableError(
                f"Ollama embedding failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        embeddings = response.json().get("embeddings")
        if not embeddings or len(embeddings) != len(texts):
            raise EmbeddingUnavailableError("Ollama returned an unexpected embedding payload")
        return np.asarray(embeddings, dtype="float32")
