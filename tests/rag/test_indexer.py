"""Index build on a temporary copy of the knowledge base with the fake embedder."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.rag.config import RagSettings, load_rag_settings
from src.rag.indexer import build_chunks, build_index
from src.rag.kb_builder import write_generated
from src.rag.store import FaissVectorStore
from tests.rag.conftest import FakeEmbedder

DOC_TYPES = {
    "rule_card",
    "context_card",
    "typology",
    "feature_dictionary",
    "operations",
}


@pytest.fixture()
def tmp_settings(tmp_path: Path) -> RagSettings:
    """Settings whose knowledge base and index live in tmp_path (repo files untouched)."""
    real = load_rag_settings()
    kb = tmp_path / "knowledge_base"
    shutil.copytree(
        real.path(real.paths.knowledge_base_dir), kb, ignore=shutil.ignore_patterns("generated")
    )
    paths = real.paths.model_copy(
        update={
            "knowledge_base_dir": str(kb),
            "generated_dir": str(kb / "generated"),
            "index_dir": str(tmp_path / "index"),
        }
    )
    settings = real.model_copy(update={"paths": paths})
    write_generated(settings)
    return settings


def test_knowledge_base_covers_all_document_types_and_rules(tmp_settings: RagSettings) -> None:
    chunks = build_chunks(tmp_settings)
    assert {c.metadata["doc_type"] for c in chunks} == DOC_TYPES
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    covered = {r for c in chunks for r in c.metadata["rule_ids"]}
    assert {f"R{n:02d}" for n in range(1, 13)} <= covered
    assert {"C1", "C9b", "G1"} <= covered
    for chunk in chunks:
        meta = chunk.metadata
        assert meta["source_path"].endswith(".md") and meta["heading_path"]


def test_typologies_link_to_rule_ids(tmp_settings: RagSettings) -> None:
    chunks = [c for c in build_chunks(tmp_settings) if c.metadata["doc_type"] == "typology"]
    sections = [c for c in chunks if len(c.metadata["heading_path"]) == 2]
    assert len(sections) == 6  # the six typologies; the intro chunk has no rule ids
    assert all(c.metadata["rule_ids"] for c in sections)


def test_build_index_saves_and_reloads(tmp_settings: RagSettings) -> None:
    store = build_index(tmp_settings, FakeEmbedder())
    reloaded = FaissVectorStore.load(tmp_settings.index_dir)
    assert len(reloaded) == len(store) > 20
