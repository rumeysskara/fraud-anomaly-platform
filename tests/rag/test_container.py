"""Container wiring: RAG providers are Singletons and can be overridden with mocks."""

from __future__ import annotations

from dependency_injector import providers

from src.container import Container
from src.rag.service import RAGService
from tests.rag.conftest import FakeEmbedder, FakeLLM


def test_rag_service_is_built_from_overridable_parts(small_store) -> None:
    container = Container()
    container.embedder.override(providers.Object(FakeEmbedder()))
    container.llm_client.override(providers.Object(FakeLLM(answer="tamam [rc#r01]")))
    container.vector_store.override(providers.Object(small_store))
    service = container.rag_service()
    assert isinstance(service, RAGService)
    assert service is container.rag_service()  # Singleton
    result = service.answer("kart testi", rule_ids=["R01"])
    assert result.answer == "tamam [rc#r01]" and result.cited_ids == ["rc#r01"]
