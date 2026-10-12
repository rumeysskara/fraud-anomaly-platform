"""Pydantic v2 request/response models of the API. No label field exists anywhere."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

# ---- transaction input -----------------------------------------------------------------------

# Extra columns accepted besides the declared ones: the V1..V339 block (the feature pipeline keeps
# a representative subset of them). Anything else is rejected, so a typo does not pass silently.
EXTRA_COLUMN = re.compile(r"^V\d{1,3}$")

EXAMPLE_TRANSACTION: dict[str, Any] = {
    "TransactionID": 3500001,
    "TransactionDT": 12500000,
    "TransactionAmt": 49.5,
    "ProductCD": "W",
    "card1": 13926,
    "card4": "visa",
    "card6": "debit",
    "addr1": 315,
    "addr2": 87,
    "P_emaildomain": "gmail.com",
    "C1": 1,
    "D1": 0,
}

_NUM = float | None
_STR = str | None


class _TransactionCore(BaseModel):
    """Required fields and the main optional raw fields of one IEEE-CIS transaction."""

    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [EXAMPLE_TRANSACTION]})

    TransactionID: int = Field(description="Unique id; /score is idempotent per id.")
    TransactionDT: int = Field(ge=0, description="Seconds offset (reference date + offset).")
    TransactionAmt: float = Field(ge=0, description="Amount in USD.")
    ProductCD: str = Field(min_length=1)
    card1: int
    card2: _NUM = None
    card3: _NUM = None
    card4: _STR = None
    card5: _NUM = None
    card6: _STR = None
    addr1: _NUM = None
    addr2: _NUM = None
    dist1: _NUM = None
    dist2: _NUM = None
    P_emaildomain: _STR = None
    R_emaildomain: _STR = None

    @model_validator(mode="after")
    def _check_extras(self) -> _TransactionCore:
        extra = self.model_extra or {}
        bad = sorted(k for k in extra if not EXTRA_COLUMN.match(k))
        if bad:
            raise ValueError(f"unknown field(s): {bad}")
        text = sorted(k for k, v in extra.items() if v is not None and not _is_number(v))
        if text:
            raise ValueError(f"V fields must be numbers or null: {text}")
        return self


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _optional_fields() -> dict[str, Any]:
    """C1-C14, D1-D15 (numeric), M1-M9 (T/F text), identity fields (all optional)."""
    fields: dict[str, Any] = {}
    for i in range(1, 15):
        fields[f"C{i}"] = (_NUM, None)
    for i in range(1, 16):
        fields[f"D{i}"] = (_NUM, None)
    for i in range(1, 10):
        fields[f"M{i}"] = (_STR, None)
    for i in range(1, 39):
        fields[f"id_{i:02d}"] = (float | str | None, None)
    fields["DeviceType"] = (_STR, None)
    fields["DeviceInfo"] = (_STR, None)
    return fields


TransactionIn = create_model("TransactionIn", __base__=_TransactionCore, **_optional_fields())
TransactionIn.__doc__ = (
    "Raw transaction. Required: TransactionID, TransactionDT, TransactionAmt, ProductCD, card1. "
    "Everything else is optional (missing = unknown). Extra V1..V339 fields are accepted."
)


# ---- shared output pieces --------------------------------------------------------------------


class ContextRuleOut(BaseModel):
    """A Step 6 context rule that changed the score (factor > 1 raises, < 1 lowers)."""

    id: str
    name: str
    factor: float
    reason: str = ""


class TriggeredRuleOut(BaseModel):
    """A Step 7 rule whose condition held."""

    id: str
    name: str
    priority: int
    severity: str
    decision: str
    risk_boost: float


class SuppressedRuleOut(BaseModel):
    """A fired rule that did not take part in the decision, with the reason."""

    id: str
    reason: str
    message: str = ""


LlmStatus = Literal["ok", "unavailable", "timeout", "empty", "error"]


# ---- /score ----------------------------------------------------------------------------------


class ScoreResponse(BaseModel):
    """Layer scores, context adjustment, rules and the final decision of one transaction."""

    transaction_id: int
    anomaly_score: float = Field(description="Normalized aggregate score in [0,1].")
    raw_anomaly_score: float = Field(description="Weighted mean of the layer scores (raw).")
    layer_scores: dict[str, float]
    adjusted_score: float = Field(description="After the context rules, clipped to [0,1].")
    context_rules: list[ContextRuleOut]
    final_score: float
    final_decision: Literal["allow", "review", "block"]
    decision_source: str = Field(description="Winning rule id, 'score' or 'default'.")
    triggered_rules: list[TriggeredRuleOut]
    suppressed_rules: list[SuppressedRuleOut]
    reasons: list[str]
    warnings: list[str] = Field(default_factory=list)
    duplicate: bool = Field(description="True: this TransactionID was scored before.")
    state_updated: bool = Field(description="True: entity history and cooldown were updated.")
    latency_ms: float


# ---- /explain --------------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    """Same transaction as /score plus an optional analyst question."""

    transaction: TransactionIn  # type: ignore[valid-type]
    question: str | None = Field(default=None, max_length=1000)


class Thresholds(BaseModel):
    """Numbers the decision was compared with (from the rule configuration)."""

    score_review: float | None
    boost_min: float
    boost_max: float


class Facts(BaseModel):
    """Deterministic part of /explain. Numbers here are the authority; the narrative is not."""

    decision: str
    decision_source: str
    final_score: float
    anomaly_score: float
    adjusted_score: float
    layer_scores: dict[str, float]
    thresholds: Thresholds
    context_rules: list[ContextRuleOut]
    triggered_rules: list[TriggeredRuleOut]
    suppressed_rules: list[SuppressedRuleOut]
    reasons: list[str]
    summary: str = Field(description="Template explanation built from the fields above.")
    warnings: list[str] = Field(default_factory=list)


class Narrative(BaseModel):
    """LLM text (RAG), labelled as supporting information. It never changes the decision."""

    label: str
    text: str
    origin: Literal["rag"] = "rag"
    affects_decision: Literal[False] = False
    grounded: bool
    abstained: bool
    sources: list[dict[str, Any]] = Field(default_factory=list)
    warning: str | None = None


class AgentInfo(BaseModel):
    """Summary of the Step 9 agent run behind the narrative."""

    status: str | None = None
    plan: list[str] = Field(default_factory=list)
    plan_source: str | None = None
    errors: list[str] = Field(default_factory=list)
    total_ms: float | None = None


class ExplainResponse(BaseModel):
    """facts (code) + narrative (LLM, optional) + trace of the agent flow."""

    transaction_id: int
    facts: Facts
    narrative: Narrative | None
    llm_status: LlmStatus
    agent: AgentInfo
    trace: list[dict[str, Any]]
    latency_ms: float


# ---- /rules ----------------------------------------------------------------------------------


class RulesEvaluateRequest(BaseModel):
    """A transaction and an optional rule set used for this request only."""

    transaction: TransactionIn  # type: ignore[valid-type]
    rules: list[dict[str, Any]] | dict[str, Any] | None = Field(
        default=None,
        description="Rule list or {'rules': [...]}; validated with the rule schema (422 if bad).",
    )


class RulesEvaluateResponse(BaseModel):
    """Rule engine result. Cooldown state is only read."""

    transaction_id: int
    rule_set: Literal["loaded", "request"]
    final_decision: str
    decision_source: str
    final_score: float
    anomaly_score: float
    adjusted_score: float
    triggered_rules: list[TriggeredRuleOut]
    suppressed_rules: list[SuppressedRuleOut]
    applied_rules: list[str]
    reasons: list[str]
    flags: list[str]
    latency_ms: float


class RuleOut(BaseModel):
    """One loaded rule (summary)."""

    id: str
    name: str
    description: str
    priority: int
    severity: str
    enabled: bool
    decision: str
    risk_boost: float
    flag: str
    cooldown_seconds: int | None = None
    tags: list[str] = Field(default_factory=list)


class RulesListResponse(BaseModel):
    """Loaded rule set."""

    count: int
    enabled_count: int
    rules: list[RuleOut]


class RulesReloadResponse(BaseModel):
    """Result of POST /rules/reload."""

    count: int
    enabled_count: int
    rule_ids: list[str]


# ---- /rag/query ------------------------------------------------------------------------------


class RagFilters(BaseModel):
    """Retrieval filters (rule ids put those rule cards first)."""

    model_config = ConfigDict(extra="forbid")

    rule_ids: list[str] = Field(default_factory=list, max_length=20)


class RagQueryRequest(BaseModel):
    """Knowledge-base question."""

    question: str = Field(min_length=3, max_length=1000)
    k: int | None = Field(default=None, ge=1, description="Number of chunks (default: config).")
    filters: RagFilters | None = None


class RagQueryResponse(BaseModel):
    """Answer with sources. answer is null when the LLM is not available (sources still there)."""

    question: str
    answer: str | None
    sources: list[dict[str, Any]]
    abstained: bool
    grounded: bool
    llm_status: LlmStatus
    flags: list[str] = Field(default_factory=list)
    warning: str | None = None
    latency_ms: float


# ---- /health ---------------------------------------------------------------------------------


class ComponentHealth(BaseModel):
    """State of one dependency."""

    ok: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """ok: all ready; degraded: /score works, LLM side not ready; down: models not loaded."""

    status: Literal["ok", "degraded", "down"]
    model_artifacts: ComponentHealth
    faiss_index: ComponentHealth
    ollama: ComponentHealth
