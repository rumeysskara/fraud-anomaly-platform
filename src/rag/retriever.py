"""Hybrid retriever: metadata match on triggered rule ids + semantic search, de-duplicated."""

from __future__ import annotations

from typing import Any

from src.core.interfaces import Embedder, Retriever
from src.core.types import Chunk
from src.rag.config import RetrievalConfig
from src.rag.store import FaissVectorStore


class HybridRetriever(Retriever):
    """Retrieves the cards of the triggered rules first, then fills up with semantic hits.

    filters (all optional):
      rule_ids  - rule ids triggered on the explained transaction (ordered by importance)
      doc_types - restrict every result to these document types
    """

    def __init__(
        self, embedder: Embedder, store: FaissVectorStore, config: RetrievalConfig
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.config = config

    def retrieve(
        self, query: str, k: int | None = None, filters: dict[str, Any] | None = None
    ) -> list[Chunk]:
        """Return up to k chunks: metadata matches first (quota), then semantic top hits."""
        k = k or self.config.k
        filters = filters or {}
        rule_ids: list[str] = list(filters.get("rule_ids") or [])
        doc_types = set(filters.get("doc_types") or [])
        query_vector = self.embedder.embed([query])[0]

        def allowed(chunk: Chunk) -> bool:
            return not doc_types or chunk.metadata.get("doc_type") in doc_types

        picked: list[Chunk] = []
        seen: set[str] = set()
        for chunk in self._metadata_hits(query_vector, rule_ids, allowed):
            if chunk.metadata["chunk_id"] not in seen and len(picked) < k:
                seen.add(chunk.metadata["chunk_id"])
                picked.append(self._tag(chunk, "metadata"))
        for chunk in self.store.search(query_vector, k + len(picked), allowed):
            if chunk.metadata["chunk_id"] not in seen and len(picked) < k:
                seen.add(chunk.metadata["chunk_id"])
                picked.append(self._tag(chunk, "semantic"))
        return picked

    def _metadata_hits(self, query_vector: Any, rule_ids: list[str], allowed: Any) -> list[Chunk]:
        """Best preferred-type chunk per triggered rule id, limited to the metadata quota."""
        preferred = set(self.config.rule_filter_doc_types)
        hits: list[Chunk] = []
        for rule_id in rule_ids[: self.config.metadata_quota]:

            def matches(chunk: Chunk, rid: str = rule_id) -> bool:
                return (
                    allowed(chunk)
                    and rid in chunk.metadata.get("rule_ids", [])
                    and (not preferred or chunk.metadata.get("doc_type") in preferred)
                )

            hits.extend(self.store.search(query_vector, 1, matches))
        return hits

    @staticmethod
    def _tag(chunk: Chunk, how: str) -> Chunk:
        """Copy of the chunk whose metadata records how it was retrieved."""
        return chunk.model_copy(update={"metadata": {**chunk.metadata, "retrieval": how}})
