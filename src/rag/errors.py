"""Exceptions of the RAG layer."""

from __future__ import annotations


class RagError(Exception):
    """Base class of all RAG errors."""


class EmbeddingUnavailableError(RagError):
    """The embedding model cannot be reached or is not installed (retrieval is impossible)."""


class LLMUnavailableError(RagError):
    """The LLM cannot be reached or is not installed (retrieval may still work)."""


class IndexNotBuiltError(RagError):
    """The FAISS index / chunk metadata is missing: run `make rag-index` first."""
