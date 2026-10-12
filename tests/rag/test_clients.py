"""Ollama embedder and LLM client against a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from src.rag.config import EmbeddingConfig, LLMConfig
from src.rag.embedder import OllamaEmbedder
from src.rag.errors import EmbeddingUnavailableError, LLMUnavailableError
from src.rag.llm import OllamaLLMClient


def client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))


EMB = EmbeddingConfig(host="http://ollama.test", model="bge-m3", timeout_seconds=5, batch_size=2)
LLM = LLMConfig(
    host="http://ollama.test",
    model="big",
    fallback_model="small",
    timeout_seconds=5,
)


def test_embedder_batches_and_returns_float32() -> None:
    sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        sizes.append(len(texts))
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0, 3.0]] * len(texts)})

    out = OllamaEmbedder(EMB, client(handler)).embed(["a", "b", "c"])
    assert out.shape == (3, 3) and out.dtype == "float32"
    assert sizes == [2, 1]


def test_embedder_connection_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(EmbeddingUnavailableError, match="unreachable"):
        OllamaEmbedder(EMB, client(handler)).embed(["a"])


def test_embedder_missing_model_message() -> None:
    with pytest.raises(EmbeddingUnavailableError, match="ollama pull bge-m3"):
        OllamaEmbedder(EMB, client(lambda r: httpx.Response(404, json={}))).embed(["a"])


def test_llm_returns_message_content_and_sends_system_context() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": " cevap "}})

    answer = OllamaLLMClient(LLM, client(handler)).generate("soru", "bağlam")
    assert answer == "cevap"
    assert seen["messages"][0] == {"role": "system", "content": "bağlam"}
    assert seen["stream"] is False and seen["options"]["temperature"] == 0.1


def test_llm_falls_back_when_primary_model_missing() -> None:
    models = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "big":
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"message": {"content": "ok"}})

    assert OllamaLLMClient(LLM, client(handler)).generate("q") == "ok"
    assert models == ["big", "small"]


def test_llm_unavailable_when_no_model_or_server() -> None:
    with pytest.raises(LLMUnavailableError, match="not installed"):
        OllamaLLMClient(LLM, client(lambda r: httpx.Response(404, json={}))).generate("q")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMUnavailableError, match="unreachable"):
        OllamaLLMClient(LLM, client(down)).generate("q")


def test_few_shot_is_part_of_the_system_context() -> None:
    from src.rag.config import PromptConfig
    from src.rag.prompt import PromptBuilder

    cfg = PromptConfig(
        system="S",
        context_header="B",
        passage="{chunk_id}",
        no_context="-",
        explanation_header="E",
        question_header="Q",
        few_shot="ÖRNEK soru cevap",
    )
    assert "ÖRNEK soru cevap" in PromptBuilder(cfg).build_context([])


def test_real_config_uses_temperature_zero_and_abstain_threshold() -> None:
    from src.rag.config import load_rag_settings

    settings = load_rag_settings()
    assert settings.llm.temperature == 0.0
    assert 0 < settings.retrieval.abstain_threshold < 1
    assert "Bilgi tabanında bu konuda bilgi yok" in settings.prompt.system
    assert settings.prompt.few_shot
