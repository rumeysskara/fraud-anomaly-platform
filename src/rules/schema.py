"""Pydantic v2 schema of a rule. An invalid rule is rejected when the rule set is loaded."""

from __future__ import annotations

import string
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Op = Literal[">", ">=", "<", "<=", "==", "!=", "in", "not_in", "between", "is_null", "contains"]
Severity = Literal["low", "medium", "high", "critical"]
Decision = Literal["block", "review", "allow"]

# Order used by conflict resolution (larger = stronger). These are the algorithm, not rules.
SEVERITY_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}
DECISION_RANK: dict[str, int] = {"allow": 1, "review": 2, "block": 3}

COMPARISON_OPS = {">", ">=", "<", "<=", "==", "!="}


def is_param_ref(value: Any) -> bool:
    """True for a {param: name} reference to a learned threshold."""
    return isinstance(value, dict) and set(value) == {"param"} and isinstance(value["param"], str)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, int | float | str | bool) or is_param_ref(value)


class Clause(BaseModel):
    """Leaf condition: {feature, op, value}."""

    model_config = ConfigDict(extra="forbid")

    feature: str
    op: Op
    value: Any = None

    @model_validator(mode="after")
    def _check_value(self) -> Clause:
        v = self.value
        if self.op in COMPARISON_OPS and not _is_scalar(v):
            raise ValueError(f"op {self.op!r} needs a scalar or {{param: name}} value, got {v!r}")
        if self.op in ("in", "not_in") and not (isinstance(v, list) and v):
            raise ValueError(f"op {self.op!r} needs a non-empty list")
        if self.op == "between":
            if not (isinstance(v, list) and len(v) == 2 and all(_is_scalar(x) for x in v)):
                raise ValueError("op 'between' needs [low, high]")
        if self.op == "is_null" and v is not None and not isinstance(v, bool):
            raise ValueError("op 'is_null' takes true/false (default true)")
        if self.op == "contains" and not isinstance(v, str):
            raise ValueError("op 'contains' needs a string")
        return self


class AllNode(BaseModel):
    """All child conditions must hold."""

    model_config = ConfigDict(extra="forbid")
    all: list[Condition] = Field(min_length=1)


class AnyNode(BaseModel):
    """At least one child condition must hold."""

    model_config = ConfigDict(extra="forbid")
    any: list[Condition] = Field(min_length=1)


class NotNode(BaseModel):
    """Negation of the child condition."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    not_: Condition = Field(alias="not")


Condition = AllNode | AnyNode | NotNode | Clause
AllNode.model_rebuild()
AnyNode.model_rebuild()
NotNode.model_rebuild()


class Action(BaseModel):
    """What a triggered rule does."""

    model_config = ConfigDict(extra="forbid")

    risk_boost: float = Field(ge=-1.0, le=1.0)
    decision: Decision
    flag: str = Field(min_length=1)


class Rule(BaseModel):
    """One configurable rule (configs/rules.yaml or a JSON file / request payload)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_\-]*$")
    name: str = Field(min_length=1)
    description: str = ""
    priority: int = Field(ge=1)
    severity: Severity
    condition: Condition
    action: Action
    message: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("message")
    @classmethod
    def _template_parses(cls, v: str) -> str:
        list(string.Formatter().parse(v))  # raises ValueError on a broken template
        return v

    @model_validator(mode="after")
    def _boost_matches_decision(self) -> Rule:
        # an allow rule may only lower (or keep) the score; block/review may only raise it
        if self.action.decision == "allow" and self.action.risk_boost > 0:
            raise ValueError(f"{self.id}: an allow rule cannot have a positive risk_boost")
        if self.action.decision != "allow" and self.action.risk_boost < 0:
            raise ValueError(f"{self.id}: a {self.action.decision} rule cannot lower the score")
        return self


def condition_features(cond: Condition) -> set[str]:
    """Feature names used anywhere in a condition tree."""
    if isinstance(cond, Clause):
        return {cond.feature}
    if isinstance(cond, NotNode):
        return condition_features(cond.not_)
    children = cond.all if isinstance(cond, AllNode) else cond.any
    return set().union(*(condition_features(c) for c in children))


def condition_params(cond: Condition) -> set[str]:
    """Learned-param names referenced anywhere in a condition tree."""
    if isinstance(cond, Clause):
        values = cond.value if isinstance(cond.value, list) else [cond.value]
        return {v["param"] for v in values if is_param_ref(v)}
    if isinstance(cond, NotNode):
        return condition_params(cond.not_)
    children = cond.all if isinstance(cond, AllNode) else cond.any
    return set().union(*(condition_params(c) for c in children))


def template_fields(message: str) -> set[str]:
    """Placeholder names in a message template, e.g. {TransactionAmt:.2f} -> TransactionAmt."""
    return {name for _, name, _, _ in string.Formatter().parse(message) if name}
