"""Ollama chat client (qwen2.5:7b). The HTTP client is injectable so tests can mock it."""

from __future__ import annotations

import logging

import httpx

from src.core.interfaces import LLMClient
from src.rag.config import LLMConfig
from src.rag.errors import LLMUnavailableError

logger = logging.getLogger(__name__)


class OllamaLLMClient(LLMClient):
    """Generates answers with a local Ollama model through POST /api/chat.

    `context` is the grounding text (instructions + retrieved passages) sent as the system
    message; `prompt` is the user message. If the primary model is not installed, the configured
    fallback model is tried once.
    """

    def __init__(self, config: LLMConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(base_url=config.host, timeout=config.timeout_seconds)

    def generate(self, prompt: str, context: str = "") -> str:
        """Return the answer; raises LLMUnavailableError if Ollama or the model is missing."""
        models = [self.config.model]
        if self.config.fallback_model:
            models.append(self.config.fallback_model)
        last_error = "no model configured"
        for model in models:
            try:
                return self._chat(model, prompt, context)
            except _ModelMissingError as exc:
                logger.warning("LLM model %s is not installed", model)
                last_error = str(exc)
        raise LLMUnavailableError(last_error)

    def _chat(self, model: str, prompt: str, context: str) -> str:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.num_ctx,
                "seed": self.config.seed,
            },
        }
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.HTTPError as exc:  # connection refused, timeout, ...
            raise LLMUnavailableError(
                f"Ollama chat endpoint unreachable ({self.config.host}): {exc}"
            ) from exc
        if response.status_code == 404:
            raise _ModelMissingError(f"LLM model '{model}' is not installed")
        if response.status_code != 200:
            raise LLMUnavailableError(
                f"Ollama chat failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        content = response.json().get("message", {}).get("content")
        if not content:
            raise LLMUnavailableError("Ollama returned an empty answer")
        return str(content).strip()


class _ModelMissingError(Exception):
    """Internal: the requested model is not installed (triggers the fallback)."""
