"""Shared interfaces for all layers. Extend only; never remove existing entries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd

from src.core.types import AdjustedResult, AgentMessage, Chunk, RuleResult


class Detector(ABC):
    """Anomaly detector (Strategy). Fitted objects are saved under artifacts/."""

    @abstractmethod
    def fit(self, df: pd.DataFrame) -> Detector:
        """Learn statistics/model from the fit set only."""

    @abstractmethod
    def score(self, df: pd.DataFrame) -> pd.Series:
        """Return anomaly scores in [0,1], indexed like df."""

    @abstractmethod
    def explain(self, row: pd.Series) -> dict[str, Any]:
        """Explain the score of a single record."""


class Aggregator(ABC):
    """Combines layer scores into one score (Strategy)."""

    @abstractmethod
    def aggregate(self, scores: dict[str, pd.Series]) -> pd.Series:
        """Return the combined score in [0,1]."""


class Normalizer(ABC):
    """Maps raw layer scores to [0,1] with a table learned on the fit set (Step 5)."""

    @abstractmethod
    def fit(self, raw: np.ndarray) -> Normalizer:
        """Learn the mapping from fit-set raw scores."""

    @abstractmethod
    def transform(self, raw: np.ndarray) -> np.ndarray:
        """Return normalized scores in [0,1]."""


class ContextAdjuster(ABC):
    """Adjusts a raw anomaly score using context."""

    @abstractmethod
    def adjust_batch(self, df: pd.DataFrame, raw_score: pd.Series) -> pd.DataFrame:
        """Adjust many rows (parquet pipeline); return a DataFrame indexed like df."""

    @abstractmethod
    def adjust_one(self, record: dict[str, Any], raw_score: float) -> AdjustedResult:
        """Adjust a single record (online API). Must share its logic with adjust_batch."""


class RuleEvaluator(ABC):
    """Applies configurable rules to a record."""

    @abstractmethod
    def evaluate(self, record: dict[str, Any], anomaly_score: float) -> RuleResult:
        """Return the final decision with triggered rules and explanations."""


class Embedder(ABC):
    """Text embedding model (local, Ollama)."""

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an array of shape (len(texts), dim)."""


class Retriever(ABC):
    """Knowledge-base retrieval."""

    @abstractmethod
    def retrieve(self, query: str, k: int = 4) -> list[Chunk]:
        """Return the top-k chunks for the query."""


class LLMClient(ABC):
    """Local LLM client (Ollama implementation)."""

    @abstractmethod
    def generate(self, prompt: str, context: str = "") -> str:
        """Return the model answer for the prompt with optional context."""


class BaseAgent(ABC):
    """Runtime agent in src/agents (not a Claude Code development agent)."""

    name: str

    @abstractmethod
    def handle(self, message: AgentMessage) -> AgentMessage:
        """Process a message and return a reply."""


class RuleStore(ABC):
    """Source of rule definitions (Repository): YAML/JSON files, reloadable (Step 7)."""

    @abstractmethod
    def reload(self) -> list[Any]:
        """Re-read and validate the rule definitions; return the loaded rules."""

    @abstractmethod
    def parse(self, payload: Any) -> list[Any]:
        """Validate a rule set given at request time and return it (not stored)."""
