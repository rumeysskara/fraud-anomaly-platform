"""FaissVectorStore: cosine search, predicate filter, save/load round trip."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.rag.errors import IndexNotBuiltError
from src.rag.store import FaissVectorStore, normalize
from tests.rag.conftest import FakeEmbedder


def test_normalize_gives_unit_rows() -> None:
    out = normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(np.linalg.norm(out[0]), 1.0)
    assert np.allclose(out[1], 0.0)


def test_search_returns_best_chunk_first(
    small_store: FaissVectorStore, embedder: FakeEmbedder
) -> None:
    query = embedder.embed(["yeni kart yüksek tutar"])[0]
    hits = small_store.search(query, 2)
    assert hits[0].metadata["chunk_id"] == "rc#r04"
    assert hits[0].score >= hits[1].score
    assert hits[0].score == pytest.approx(1.0, abs=0.35)


def test_search_predicate_filters_exactly(
    small_store: FaissVectorStore, embedder: FakeEmbedder
) -> None:
    query = embedder.embed(["kart testi"])[0]
    hits = small_store.search(query, 10, lambda c: c.metadata["doc_type"] == "operations")
    assert [h.metadata["chunk_id"] for h in hits] == ["ops#block"]


def test_save_and_load_round_trip(
    small_store: FaissVectorStore, embedder: FakeEmbedder, tmp_path: Path
) -> None:
    small_store.save(tmp_path / "rag")
    loaded = FaissVectorStore.load(tmp_path / "rag")
    query = embedder.embed(["kart testi"])[0]
    before = [(c.metadata["chunk_id"], round(c.score, 5)) for c in small_store.search(query, 3)]
    after = [(c.metadata["chunk_id"], round(c.score, 5)) for c in loaded.search(query, 3)]
    assert before == after
    assert len(loaded) == len(small_store)


def test_load_missing_index_raises_meaningful_error(tmp_path: Path) -> None:
    with pytest.raises(IndexNotBuiltError, match="rag-index"):
        FaissVectorStore.load(tmp_path / "nothing")
