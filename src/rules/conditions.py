"""Vectorized evaluation of the condition DSL. A single record is a one-row DataFrame."""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from src.rules.schema import AllNode, AnyNode, Clause, Condition, NotNode, is_param_ref

_COMPARE: dict[str, Callable[[Any, Any], Any]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def resolve_value(value: Any, params: dict[str, Any]) -> Any:
    """Replace {param: name} (also inside lists) with the learned value."""
    if is_param_ref(value):
        name = value["param"]
        if name not in params:
            raise KeyError(f"rule param {name!r} is not available; run scripts/run_rules.py")
        return params[name]
    if isinstance(value, list):
        return [resolve_value(v, params) for v in value]
    return value


def _clause(clause: Clause, df: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    column = df[clause.feature]
    present = column.notna().to_numpy()
    value = resolve_value(clause.value, params)
    op = clause.op
    if op == "is_null":
        return ~present if value in (None, True) else present
    # a missing value never satisfies a comparison: only present rows are compared
    out = np.zeros(len(df), dtype=bool)
    s = column[present]
    if s.empty:
        return out
    if op in _COMPARE:
        result = _COMPARE[op](s, value)
    elif op == "in":
        result = s.isin(value)
    elif op == "not_in":
        result = ~s.isin(value)
    elif op == "between":
        low, high = value
        result = (s >= low) & (s <= high)
    else:  # contains
        result = s.astype(str).str.contains(value, regex=False)
    out[present] = np.asarray(result, dtype=bool)
    return out


def evaluate_condition(cond: Condition, df: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    """Boolean array (one value per row of df) for a condition tree."""
    if isinstance(cond, Clause):
        return _clause(cond, df, params)
    if isinstance(cond, NotNode):
        return ~evaluate_condition(cond.not_, df, params)
    if isinstance(cond, AllNode):
        out = np.ones(len(df), dtype=bool)
        for child in cond.all:
            out &= evaluate_condition(child, df, params)
        return out
    assert isinstance(cond, AnyNode)
    out = np.zeros(len(df), dtype=bool)
    for child in cond.any:
        out |= evaluate_condition(child, df, params)
    return out
