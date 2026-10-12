"""Typed access to configs/rag.yaml (pydantic v2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.core.config import CONFIG_DIR, ROOT_DIR, load_yaml


class PathsConfig(BaseModel):
    """Locations used by the builder, the indexer and the service (relative to the repo root)."""

    knowledge_base_dir: str
    generated_dir: str
    rule_notes: str
    context_params: str
    index_dir: str


class EmbeddingConfig(BaseModel):
    """Ollama embedding model settings."""

    host: str
    model: str
    timeout_seconds: float
    batch_size: int = 16


class LLMConfig(BaseModel):
    """Ollama chat model settings."""

    host: str
    model: str
    fallback_model: str | None = None
    timeout_seconds: float
    temperature: float = 0.1
    num_ctx: int = 4096
    seed: int = 42


class ChunkingConfig(BaseModel):
    """Safety cap for chunk size (structure-aware chunking never cuts by characters)."""

    max_tokens: int
    chars_per_token: float


class RetrievalConfig(BaseModel):
    """Hybrid retrieval settings."""

    k: int = 4
    metadata_quota: int = 2
    rule_filter_doc_types: list[str] = Field(default_factory=list)


class PromptConfig(BaseModel):
    """Prompt template pieces."""

    system: str
    context_header: str
    passage: str
    no_context: str
    explanation_header: str
    question_header: str
    answer_reminder: str = ""
    explanation_keys: list[str] = Field(default_factory=list)


class RagSettings(BaseModel):
    """Whole configs/rag.yaml."""

    seed: int = 42
    paths: PathsConfig
    embedding: EmbeddingConfig
    llm: LLMConfig
    chunking: ChunkingConfig
    retrieval: RetrievalConfig
    prompt: PromptConfig
    operator_labels: dict[str, str] = Field(default_factory=dict)
    feature_labels: dict[str, str] = Field(default_factory=dict)

    def path(self, relative: str) -> Path:
        """Resolve a config path against the repository root."""
        return ROOT_DIR / relative

    @property
    def index_dir(self) -> Path:
        """Absolute index directory."""
        return self.path(self.paths.index_dir)


def load_rag_settings(config_dir: Path = CONFIG_DIR) -> RagSettings:
    """Load and validate configs/rag.yaml."""
    data: dict[str, Any] = load_yaml("rag.yaml", config_dir)
    return RagSettings.model_validate(data)
