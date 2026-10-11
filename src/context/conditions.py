"""Tiny condition language of configs/context.yaml: `all:` of {feature, op, value} clauses."""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from src.context.params import ContextParams

COMPARISONS: dict[str, Callable[[Any, Any], Any]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}
UNARY = ("isna", "notna")


def clause_features(condition: dict[str, Any]) -> list[str]:
    """Columns a condition reads (to check that inputs are complete)."""
    return [c["feature"] for c in condition.get("all", [])]


def _value(raw: Any, params: ContextParams) -> Any:
    """Resolve {param: name} to the learned value; plain values pass through."""
    if isinstance(raw, dict) and "param" in raw:
        return params.get(raw["param"])
    return raw


def eval_clause(df: pd.DataFrame, clause: dict[str, Any], params: ContextParams) -> np.ndarray:
    """Boolean mask of one clause. NaN satisfies only `isna`."""
    col = df[clause["feature"]]
    op = clause["op"]
    if op == "isna":
        return col.isna().to_numpy()
    if op == "notna":
        return col.notna().to_numpy()
    present = col.notna().to_numpy()
    value = _value(clause.get("value"), params)
    if op == "in":
        mask = col.isin(list(value)).to_numpy()
    elif op in COMPARISONS:
        if isinstance(col.dtype, pd.CategoricalDtype):
            col = col.astype(object)
        mask = np.asarray(COMPARISONS[op](col, value), dtype=bool)
    else:
        raise ValueError(f"unknown operator {op!r}")
    return mask & present


def eval_condition(
    df: pd.DataFrame, condition: dict[str, Any], params: ContextParams
) -> np.ndarray:
    """AND of all clauses (an empty condition is always true)."""
    mask = np.ones(len(df), dtype=bool)
    for clause in condition.get("all", []):
        mask &= eval_clause(df, clause, params)
    return mask
