"""Hybrid retrieval: metadata (rule id) slots + semantic fill, de-duplicated."""

from __future__ import annotations

from src.rag.config import RetrievalConfig
from src.rag.retriever import HybridRetriever
from src.rag.store import FaissVectorStore
from tests.rag.conftest import FakeEmbedder

CONFIG = RetrievalConfig(k=4, metadata_quota=2, rule_filter_doc_types=["rule_card"])


def make(store: FaissVectorStore, embedder: FakeEmbedder) -> HybridRetriever:
    return HybridRetriever(embedder, store, CONFIG)


def ids(chunks: list) -> list[str]:
    return [c.metadata["chunk_id"] for c in chunks]


def test_semantic_only_without_filters(small_store, embedder) -> None:
    result = make(small_store, embedder).retrieve("yeni kart yüksek tutar", 3)
    assert ids(result)[0] == "rc#r04"
    assert all(c.metadata["retrieval"] == "semantic" for c in result)


def test_rule_filter_forces_the_rule_card_even_if_semantically_weak(small_store, embedder) -> None:
    # The query is about the foreign-country topic; R04's card is not the best semantic match.
    result = make(small_store, embedder).retrieve(
        "block kararında analist ne yapar", 3, {"rule_ids": ["R04"]}
    )
    assert ids(result)[0] == "rc#r04"
    assert result[0].metadata["retrieval"] == "metadata"


def test_duplicates_are_removed(small_store, embedder) -> None:
    result = make(small_store, embedder).retrieve("kart testi", 4, {"rule_ids": ["R01"]})
    assert len(ids(result)) == len(set(ids(result)))
    assert ids(result).count("rc#r01") == 1
    assert result[0].metadata["chunk_id"] == "rc#r01"  # metadata slot first, not repeated later


def test_metadata_quota_and_k_limit(small_store, embedder) -> None:
    result = make(small_store, embedder).retrieve("kart", 3, {"rule_ids": ["R01", "R04", "R02"]})
    assert len(result) == 3
    assert [c.metadata["retrieval"] for c in result].count("metadata") == 2  # quota = 2


def test_doc_type_filter_restricts_everything(small_store, embedder) -> None:
    result = make(small_store, embedder).retrieve("kart testi", 4, {"doc_types": ["typology"]})
    assert ids(result) == ["ty#card"]


def test_unknown_rule_id_falls_back_to_semantic(small_store, embedder) -> None:
    result = make(small_store, embedder).retrieve("kart testi", 2, {"rule_ids": ["R99"]})
    assert len(result) == 2
    assert all(c.metadata["retrieval"] == "semantic" for c in result)
