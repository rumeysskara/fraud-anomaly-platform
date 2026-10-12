"""Startup warm-up of the Ollama models (K-50): background thread, recorded state, /health."""

from __future__ import annotations

import json
import time

import httpx

from src.api.config import ApiSettings, WarmupSettings
from src.api.warmup import ModelWarmer
from src.rag.config import EmbeddingConfig, LLMConfig
from src.rag.embedder import OllamaEmbedder
from src.rag.llm import OllamaLLMClient
from tests.api.conftest import WarmEmbedder, WarmLLM, World, make_client


def test_warm_up_calls_both_models_and_records_ok() -> None:
    embedder, llm = WarmEmbedder(), WarmLLM()
    warmer = ModelWarmer(embedder, llm, ApiSettings())
    warmer.start()
    warmer.join(5)
    state = warmer.state()
    assert state["embedding"]["status"] == "ok" and state["llm"]["status"] == "ok"
    assert "duration_ms" in state["llm"] and warmer.ready()
    assert embedder.calls == [["warm-up"]] and len(llm.calls) == 1


def test_start_does_not_block_and_runs_once() -> None:
    warmer = ModelWarmer(WarmEmbedder(delay=0.5), WarmLLM(), ApiSettings())
    started = time.perf_counter()
    warmer.start()
    warmer.start()  # second call is a no-op
    assert time.perf_counter() - started < 0.2
    assert warmer.state()["embedding"]["status"] == "running" and not warmer.ready()
    warmer.join(5)
    assert warmer.ready()


def test_failures_are_recorded_not_raised() -> None:
    warmer = ModelWarmer(WarmEmbedder(fail=True), WarmLLM(fail=True), ApiSettings())
    warmer.run()
    state = warmer.state()
    assert (
        state["embedding"]["status"] == "error" and "embedding down" in state["embedding"]["error"]
    )
    assert state["llm"]["status"] == "error"  # the LLM is still tried after an embedding failure
    assert not warmer.ready()


def test_disabled_warm_up_never_calls_ollama() -> None:
    embedder, llm = WarmEmbedder(), WarmLLM()
    warmer = ModelWarmer(embedder, llm, ApiSettings(warmup=WarmupSettings(enabled=False)))
    warmer.start()
    warmer.join(1)
    assert warmer.state()["llm"]["status"] == "disabled" and embedder.calls == []


def test_app_startup_starts_warm_up_and_health_shows_it(world: World) -> None:
    for client in make_client(world):
        world.warmer.join(5)
        data = client.get("/health").json()
        assert data["warmup"]["ok"] is True
        assert data["warmup"]["detail"]["llm"]["status"] == "ok"
        assert data["status"] == "ok"


def test_health_warm_up_error_does_not_change_status(world: World) -> None:
    world.warmer = ModelWarmer(WarmEmbedder(), WarmLLM(fail=True), world.api_settings)
    for client in make_client(world):
        world.warmer.join(5)
        data = client.get("/health").json()
        assert data["warmup"]["ok"] is False and data["status"] == "ok"


def test_keep_alive_is_sent_to_ollama() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0]]})
        return httpx.Response(200, json={"message": {"content": "tamam"}})

    http = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    emb = EmbeddingConfig(host="http://ollama.test", model="bge-m3", timeout_seconds=5)
    llm = LLMConfig(host="http://ollama.test", model="m", timeout_seconds=5, keep_alive="10m")
    OllamaEmbedder(emb, http).embed(["a"])
    OllamaLLMClient(llm, http).generate("q")
    assert bodies[0]["keep_alive"] == "30m" and bodies[1]["keep_alive"] == "10m"
