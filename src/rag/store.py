"""FAISS vector store (IndexFlatIP over L2-normalized vectors = cosine similarity).

The index and the chunk metadata are written once by the offline indexer to artifacts/rag/ and
only loaded at runtime. The knowledge base is small, so exact (flat) search is used.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import faiss
import numpy as np

from src.core.types import Chunk
from src.rag.config import RagSettings
from src.rag.errors import IndexNotBuiltError

logger = logging.getLogger(__name__)

INDEX_FILE = "index.faiss"
CHUNKS_FILE = "chunks.jsonl"


def normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows (float32); zero rows stay zero."""
    vectors = np.ascontiguousarray(vectors, dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


class FaissVectorStore:
    """Chunks plus their normalized vectors; search returns chunks with a cosine score."""

    def __init__(self, index: faiss.Index, chunks: list[Chunk]) -> None:
        if index.ntotal != len(chunks):
            raise ValueError("index size and chunk count differ")
        self.index = index
        self.chunks = chunks

    @classmethod
    def from_vectors(cls, chunks: list[Chunk], vectors: np.ndarray) -> FaissVectorStore:
        """Build a store from chunks and their (unnormalized) embeddings."""
        if len(chunks) != len(vectors) or len(chunks) == 0:
            raise ValueError("need one vector per chunk and at least one chunk")
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(normalize(vectors))
        return cls(index, list(chunks))

    def __len__(self) -> int:
        return len(self.chunks)

    def search(
        self,
        query_vector: np.ndarray,
        k: int,
        predicate: Callable[[Chunk], bool] | None = None,
    ) -> list[Chunk]:
        """Top-k chunks by cosine score, optionally only those accepted by `predicate`.

        Flat search scores every chunk, so the predicate is applied exactly (no recall loss).
        """
        query = normalize(np.asarray(query_vector, dtype="float32").reshape(1, -1))
        scores, ids = self.index.search(query, self.index.ntotal)
        results: list[Chunk] = []
        for score, idx in zip(scores[0], ids[0], strict=True):
            if idx < 0:
                continue
            chunk = self.chunks[int(idx)]
            if predicate is not None and not predicate(chunk):
                continue
            results.append(chunk.model_copy(update={"score": float(score)}))
            if len(results) == k:
                break
        return results

    def save(self, directory: Path) -> None:
        """Write index.faiss and chunks.jsonl into `directory`."""
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(directory / INDEX_FILE))
        with open(directory / CHUNKS_FILE, "w", encoding="utf-8") as f:
            for chunk in self.chunks:
                f.write(json.dumps(chunk.model_dump(exclude={"score"}), ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, directory: Path) -> FaissVectorStore:
        """Load a saved store; raises IndexNotBuiltError when the files are missing."""
        index_path, chunks_path = directory / INDEX_FILE, directory / CHUNKS_FILE
        if not index_path.exists() or not chunks_path.exists():
            raise IndexNotBuiltError(f"RAG index not found in {directory} (run: make rag-index)")
        index = faiss.read_index(str(index_path))
        with open(chunks_path, encoding="utf-8") as f:
            chunks = [Chunk.model_validate(json.loads(line)) for line in f if line.strip()]
        return cls(index, chunks)


def load_vector_store(settings: RagSettings) -> FaissVectorStore:
    """Load the store from settings.index_dir (container factory)."""
    return FaissVectorStore.load(settings.index_dir)
