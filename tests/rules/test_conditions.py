"""Condition DSL operators on a small synthetic frame."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.rules.conditions import evaluate_condition
from src.rules.schema import AllNode, Rule

DF = pd.DataFrame(
    {
        "amt": [10.0, 50.0, np.nan, 500.0],
        "product": ["W", "C", "H", None],
        "email": ["gmail.com", "yahoo.com", None, "mail.gmail.com"],
    }
)


def cond(raw: dict):
    return Rule.model_validate(
        {
            "id": "T",
            "name": "t",
            "priority": 1,
            "severity": "low",
            "condition": raw,
            "action": {"risk_boost": 0.0, "decision": "review", "flag": "t"},
            "message": "m",
        }
    ).condition


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"feature": "amt", "op": ">", "value": 20}, [0, 1, 0, 1]),
        ({"feature": "amt", "op": "<=", "value": 50}, [1, 1, 0, 0]),
        ({"feature": "amt", "op": "!=", "value": 10}, [0, 1, 0, 1]),  # NaN never matches
        ({"feature": "amt", "op": "between", "value": [10, 50]}, [1, 1, 0, 0]),
        ({"feature": "amt", "op": "is_null"}, [0, 0, 1, 0]),
        ({"feature": "amt", "op": "is_null", "value": False}, [1, 1, 0, 1]),
        ({"feature": "product", "op": "in", "value": ["C", "H"]}, [0, 1, 1, 0]),
        ({"feature": "product", "op": "not_in", "value": ["C", "H"]}, [1, 0, 0, 0]),
        ({"feature": "email", "op": "contains", "value": "gmail"}, [1, 0, 0, 1]),
        ({"feature": "amt", "op": ">", "value": {"param": "limit"}}, [0, 0, 0, 1]),
        (
            {
                "any": [
                    {"feature": "amt", "op": "<", "value": 20},
                    {"feature": "product", "op": "==", "value": "H"},
                ]
            },
            [1, 0, 1, 0],
        ),
        ({"not": {"feature": "amt", "op": ">", "value": 20}}, [1, 0, 1, 0]),
        (
            {
                "all": [
                    {"feature": "amt", "op": ">", "value": 20},
                    {"not": {"feature": "product", "op": "==", "value": "C"}},
                ]
            },
            [0, 0, 0, 1],
        ),
    ],
)
def test_operators(raw, expected):
    out = evaluate_condition(cond(raw), DF, {"limit": 100.0})
    assert out.tolist() == [bool(x) for x in expected]


def test_nested_node_types():
    assert isinstance(cond({"all": [{"feature": "amt", "op": ">", "value": 1}]}), AllNode)


def test_missing_param_is_an_error():
    with pytest.raises(KeyError, match="limit"):
        evaluate_condition(cond({"feature": "amt", "op": ">", "value": {"param": "limit"}}), DF, {})


def test_none_in_object_column_never_matches():
    df = pd.DataFrame({"amt": [None]}, dtype=object)
    assert evaluate_condition(cond({"feature": "amt", "op": ">", "value": 1}), df, {}).tolist() == [
        False
    ]
