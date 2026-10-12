"""Offline index build: knowledge base markdown -> chunks -> embeddings -> FAISS (artifacts/rag)."""

from __future__ import annotations

import logging

from src.core.config import set_seed
from src.core.interfaces import Embedder
from src.core.types import Chunk
from src.rag.chunker import chunk_markdown
from src.rag.config import RagSettings
from src.rag.store import FaissVectorStore

logger = logging.getLogger(__name__)


def build_chunks(settings: RagSettings) -> list[Chunk]:
    """Chunk every markdown file under the knowledge base folder (sorted, deterministic)."""
    root = settings.path(settings.paths.knowledge_base_dir)
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root.parent).as_posix()
        chunks.extend(
            chunk_markdown(
                path.read_text(encoding="utf-8"),
                relative,
                settings.chunking.max_tokens,
                settings.chunking.chars_per_token,
            )
        )
    ids = [c.metadata["chunk_id"] for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate chunk ids in the knowledge base")
    return chunks


def build_index(settings: RagSettings, embedder: Embedder) -> FaissVectorStore:
    """Embed all chunks, build the FAISS store and save it to settings.index_dir."""
    set_seed(settings.seed)
    chunks = build_chunks(settings)
    logger.info("embedding %d chunks with %s", len(chunks), settings.embedding.model)
    store = FaissVectorStore.from_vectors(chunks, embedder.embed([c.text for c in chunks]))
    store.save(settings.index_dir)
    return store
