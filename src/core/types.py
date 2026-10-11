"""Shared pydantic models passed between layers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Explanation(BaseModel):
    """Human-readable reason attached to a score or decision."""

    source: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ScoreResult(BaseModel):
    """Anomaly score of one record: normalized in [0,1] plus the raw value."""

    transaction_id: int | None = None
    score: float = Field(ge=0.0, le=1.0)
    raw_score: float
    layer_scores: dict[str, float] = Field(default_factory=dict)
    explanations: list[Explanation] = Field(default_factory=list)


class AdjustedResult(BaseModel):
    """Output of context-aware score adjustment."""

    raw_score: float
    adjusted_score: float = Field(ge=0.0, le=1.0)
    applied_rules: list[str] = Field(default_factory=list)
    explanations: list[Explanation] = Field(default_factory=list)


class RuleResult(BaseModel):
    """Output of the rule engine for one record."""

    action: str  # e.g. "allow" | "review" | "block"
    final_score: float = Field(ge=0.0, le=1.0)
    triggered_rules: list[str] = Field(default_factory=list)
    explanations: list[Explanation] = Field(default_factory=list)


class Chunk(BaseModel):
    """A retrieved knowledge-base passage."""

    text: str
    source: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    """Message exchanged between runtime agents."""

    sender: str
    recipient: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
