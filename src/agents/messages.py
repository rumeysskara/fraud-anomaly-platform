"""Typed messages exchanged on the bus (pydantic v2), request/reply payloads and the response."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.types import AgentMessage

Status = Literal["ok", "error", "skipped"]

# Agent names and intents (the allowed set per role is configured in configs/agents.yaml).
COORDINATOR = "coordinator"
ANOMALY = "anomaly"
CONTEXT = "context"
RULE = "rule"
EXPLAINER = "explainer"
FEATURE = "feature"  # internal: reached only by delegation from the anomaly agent
CLIENT = "client"

INTENT_ANALYZE = "analyze"
INTENT_SCORE = "score"
INTENT_ADJUST = "adjust"
INTENT_EVALUATE = "evaluate"
INTENT_EXPLAIN = "explain"
INTENT_FEATURIZE = "featurize"


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class BusMessage(AgentMessage):
    """One message on the bus. Extends the shared AgentMessage (sender, recipient, payload)."""

    message_id: str = Field(default_factory=_new_id)
    correlation_id: str = Field(default_factory=_new_id)  # one value per analyst request
    parent_id: str | None = None  # message being handled when this one was sent (delegation)
    intent: str
    content: str = ""
    timestamp: datetime = Field(default_factory=_now)
    status: Status = "ok"
    depth: int = 0  # delegation depth, limited by the bus

    def reply(self, payload: dict[str, Any], status: Status = "ok") -> BusMessage:
        """Reply to this message (same correlation id and intent, sender/recipient swapped)."""
        return BusMessage(
            sender=self.recipient,
            recipient=self.sender,
            intent=self.intent,
            correlation_id=self.correlation_id,
            parent_id=self.message_id,
            payload=payload,
            status=status,
            depth=self.depth,
        )


class TraceEntry(BaseModel):
    """Who sent what to whom, how long it took and how it ended."""

    seq: int
    message_id: str
    parent_id: str | None = None
    sender: str
    recipient: str
    intent: str
    status: str  # ok | error | skipped (or "pending" while the call runs)
    duration_ms: float = 0.0  # includes nested delegations
    timestamp: datetime
    payload_keys: list[str] = Field(default_factory=list)  # keys only: records are large
    detail: str | None = None  # error text or event note


# ---- payloads (validated by the receiving agent) ----------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _RecordOrTransaction(BaseModel):
    """`record` = ready record (features + raw fields); `transaction` = raw payload.

    Exactly one is needed. With only a transaction the anomaly agent asks the feature agent to
    build the record (delegation); the record then travels back in the replies.
    """

    record: dict[str, Any] | None = None
    transaction: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_input(self) -> _RecordOrTransaction:
        if (self.record is None) == (self.transaction is None):
            raise ValueError("give exactly one of record or transaction")
        return self


class AnalystRequest(_RecordOrTransaction):
    """What the caller (API, script) gives the coordinator."""

    question: str | None = None  # free-text analyst task; None -> deterministic default plan

    @property
    def transaction_id(self) -> int | None:
        """TransactionID of the record or the raw transaction."""
        tid = (self.record or self.transaction or {}).get("TransactionID")
        return int(tid) if tid is not None else None


class FeaturizeRequest(_Strict):
    """feature.featurize: raw transaction -> record (Step 3 FeaturePipeline.transform_one)."""

    transaction: dict[str, Any]


class FeaturizeReply(_Strict):
    """The record the Step 4-7 services expect."""

    record: dict[str, Any]


class ScoreRequest(_Strict, _RecordOrTransaction):
    """anomaly.score: a ready record, or a raw transaction that is featurized first."""


class ScoreReply(_Strict):
    """Step 4-5 scores: anomaly_score is the normalized aggregate in [0,1]."""

    anomaly_score: float
    raw_score: float
    layer_scores: dict[str, float]
    explanations: list[dict[str, Any]] = Field(default_factory=list)
    record: dict[str, Any] | None = None  # set only when the anomaly agent featurized


class AdjustRequest(_Strict, _RecordOrTransaction):
    """context.adjust: score inputs are optional (missing ones come from the anomaly agent)."""

    anomaly_score: float | None = None
    layer_scores: dict[str, float] | None = None


class AdjustReply(_Strict):
    """Step 6 result. adjusted_score_unclipped is the score the rules boost."""

    anomaly_score: float
    layer_scores: dict[str, float]
    adjusted_score: float
    adjusted_score_unclipped: float
    applied_rules: list[str]
    explanations: list[dict[str, Any]] = Field(default_factory=list)
    record: dict[str, Any] | None = None  # set only when the record was built in a delegation


class EvaluateRequest(_Strict, _RecordOrTransaction):
    """rule.evaluate: missing scores are requested from the context agent (which asks anomaly)."""

    anomaly_score: float | None = None
    layer_scores: dict[str, float] | None = None
    adjusted_score: float | None = None
    adjusted_score_unclipped: float | None = None


class EvaluateReply(_Strict):
    """Step 7 result: the final decision lives here and nowhere else."""

    final_decision: str
    decision_source: str
    final_score: float
    triggered_rules: list[str]
    applied_rules: list[str]
    suppressed_rules: list[dict[str, str]]
    reasons: list[str]
    explain: dict[str, Any]  # RuleEngineResult.explain_dict()
    # scores the rule engine was given (filled from the delegation when the rule agent asked)
    anomaly_score: float | None = None
    adjusted_score: float | None = None
    layer_scores: dict[str, float] = Field(default_factory=dict)
    context_rules: list[str] = Field(default_factory=list)


class ExplainRequest(_Strict):
    """explain: the rule result comes from the rule agent; the question is optional."""

    rule_result: EvaluateReply
    question: str | None = None
    layer_scores: dict[str, float] = Field(default_factory=dict)
    context_rules: list[str] = Field(default_factory=list)


class ExplainReply(_Strict):
    """Step 8 RAG answer, labelled as supporting information. It never changes the decision."""

    label: str
    affects_decision: Literal[False] = False
    origin: Literal["rag", "template"] = "rag"  # template: RAG answer was empty (K-39)
    text: str | None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    cited_ids: list[str] = Field(default_factory=list)
    grounded: bool = False
    abstained: bool = False
    flags: list[str] = Field(default_factory=list)
    warning: str | None = None


# ---- coordinator output ------------------------------------------------------------------------


class PlanInfo(BaseModel):
    """The plan that was executed and where it came from."""

    source: Literal["default", "llm", "fallback"]
    steps: list[str]  # "agent:intent"
    fallback_reason: str | None = None
    duration_ms: float = 0.0  # time spent planning (LLM call; ~0 for the default plan)


class AgentResponse(BaseModel):
    """Final answer for one request. `decision` comes only from the rule agent."""

    correlation_id: str
    transaction_id: int | None = None
    status: Literal["ok", "degraded", "error"]  # degraded: decision present, a helper failed
    decision: str | None = None
    decision_source: str | None = None
    final_score: float | None = None
    anomaly_score: float | None = None
    adjusted_score: float | None = None
    layer_scores: dict[str, float] = Field(default_factory=dict)
    context_rules: list[str] = Field(default_factory=list)
    triggered_rules: list[str] = Field(default_factory=list)
    suppressed_rules: list[dict[str, str]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    explanation: ExplainReply | None = None
    plan: PlanInfo
    errors: list[str] = Field(default_factory=list)
    total_ms: float = 0.0
    trace: list[TraceEntry] = Field(default_factory=list)
