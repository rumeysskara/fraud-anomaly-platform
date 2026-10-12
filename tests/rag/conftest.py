"""Shared fakes for RAG tests: no Ollama, no real models."""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest

from src.core.interfaces import Embedder, LLMClient
from src.core.types import Chunk
from src.rag.errors import EmbeddingUnavailableError, LLMUnavailableError
from src.rag.store import FaissVectorStore

DIM = 128


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked `ollama` run only when explicitly selected with `-m ollama`."""
    if "ollama" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="needs Ollama; run with: pytest -m ollama")
    for item in items:
        if "ollama" in item.keywords:
            item.add_marker(skip)


class FakeEmbedder(Embedder):
    """Bag-of-words hashing embedder: texts sharing words get a high cosine."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        if self.fail:
            raise EmbeddingUnavailableError("fake embedder is down")
        out = np.zeros((len(texts), DIM), dtype="float32")
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        return out


class FakeLLM(LLMClient):
    """Records the last call and returns a canned answer, or raises when down."""

    def __init__(self, answer: str = "cevap [a#b]", down: bool = False) -> None:
        self.answer = answer
        self.down = down
        self.last_prompt = ""
        self.last_context = ""

    def generate(self, prompt: str, context: str = "") -> str:
        if self.down:
            raise LLMUnavailableError("fake llm is down")
        self.last_prompt, self.last_context = prompt, context
        return self.answer


def make_chunk(chunk_id: str, text: str, doc_type: str, rule_ids: list[str]) -> Chunk:
    """A chunk with the metadata the indexer would produce."""
    return Chunk(
        text=text,
        source=f"knowledge_base/{doc_type}.md",
        metadata={
            "chunk_id": chunk_id,
            "doc_type": doc_type,
            "rule_ids": rule_ids,
            "source_path": f"knowledge_base/{doc_type}.md",
            "heading_path": ["Doc", chunk_id],
        },
    )


@pytest.fixture()
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture()
def small_store(embedder: FakeEmbedder) -> FaissVectorStore:
    """Five chunks: two rule cards, a typology, an ops section, a feature entry."""
    chunks = [
        make_chunk("rc#r01", "kart testi küçük tutar art arda işlem", "rule_card", ["R01"]),
        make_chunk("rc#r04", "yeni kart yüksek tutar bust out", "rule_card", ["R04"]),
        make_chunk("ty#card", "kart testi tipolojisi küçük tutarlar denenir", "typology", ["R01"]),
        make_chunk("ops#block", "block kararında analist müşteriyi arar", "operations", ["R01"]),
        make_chunk("fd#amt", "tutar feature sözlüğü işlem tutarı", "feature_dictionary", []),
    ]
    return FaissVectorStore.from_vectors(chunks, embedder.embed([c.text for c in chunks]))
