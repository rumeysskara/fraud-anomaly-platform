"""Labelled rule metrics on a tiny synthetic example."""

from __future__ import annotations

import pandas as pd
import pytest

from src.evaluation.rule_metrics import (
    budget_table,
    decision_metrics,
    lift_by_group,
    rule_hit_metrics,
)

Y = pd.Series([1, 0, 0, 0, 1, 0, 0, 0], index=range(8))


def test_rule_hit_metrics():
    hits = pd.DataFrame({"A": [1, 1, 0, 0, 0, 0, 0, 0], "B": [0] * 8}, index=Y.index)
    applied = pd.DataFrame({"A": [1, 0, 0, 0, 0, 0, 0, 0], "B": [0] * 8}, index=Y.index)
    m = rule_hit_metrics(Y, hits, applied).set_index("id")
    assert m.at["A", "hits"] == 2 and m.at["A", "tp"] == 1
    assert m.at["A", "precision"] == 0.5 and m.at["A", "lift"] == pytest.approx(2.0)
    assert m.at["A", "precision_applied"] == 1.0
    assert m.at["B", "hits"] == 0 and pd.isna(m.at["B", "precision"])


def test_decision_metrics():
    decision = pd.Series(["block", "allow", "allow", "allow", "review", "review", "allow", "allow"])
    m = decision_metrics(Y, decision).set_index("final_decision")
    assert m.at["block", "tp"] == 1 and m.at["block", "fp"] == 0
    assert m.at["review", "precision"] == 0.5 and m.at["allow", "rows"] == 5


def test_budget_table():
    good = pd.Series([0.9, 0.1, 0.2, 0.3, 0.8, 0.0, 0.0, 0.0], index=Y.index)
    t = budget_table(Y, {"good": good, "bad": 1 - good}, [0.25])
    row = t.set_index("score").loc["good"]
    assert row["alarms"] == 2 and row["tp"] == 2 and row["fp"] == 0 and row["recall"] == 1.0
    assert t.set_index("score").loc["bad", "tp"] == 0


def test_lift_by_group_removes_group_mix():
    # the condition marks group g1 only; inside g1 it is no better than the group base rate
    y = pd.Series([1, 1, 0, 0, 0, 0, 0, 0], index=range(8))
    group = pd.Series(["g1"] * 4 + ["g2"] * 4, index=y.index)
    masks = pd.DataFrame({"cond": [1, 1, 0, 0, 0, 0, 0, 0]}, index=y.index).astype(bool)
    masks.loc[2:3, "cond"] = True
    t = lift_by_group(y, masks, group).set_index("group")
    assert t.at["ALL", "lift_in_group"] == pytest.approx(2.0)
    assert t.at["g1", "lift_in_group"] == pytest.approx(1.0)
    assert t.at["g2", "hits"] == 0
