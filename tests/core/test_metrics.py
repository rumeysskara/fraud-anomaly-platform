"""Evaluation metric tests on synthetic labels/scores."""

import pandas as pd

from src.evaluation.metrics import (
    compare_false_positives,
    evaluate,
    false_positives_at_budget,
    pr_auc,
    precision_at_k,
    recall_at_k,
    roc_auc,
)

Y = pd.Series([1, 0, 0, 1, 0, 0, 0, 0, 0, 0], index=range(10))
GOOD = pd.Series([0.9, 0.1, 0.2, 0.8, 0.3, 0.0, 0.1, 0.2, 0.1, 0.0], index=range(10))
BAD = pd.Series([0.1, 0.9, 0.8, 0.2, 0.3, 0.0, 0.1, 0.2, 0.1, 0.0], index=range(10))


def test_perfect_ranking():
    assert roc_auc(Y, GOOD) == 1.0
    assert pr_auc(Y, GOOD) == 1.0
    assert precision_at_k(Y, GOOD, 2) == 1.0
    assert recall_at_k(Y, GOOD, 2) == 1.0


def test_bad_ranking():
    assert recall_at_k(Y, BAD, 2) == 0.0
    assert false_positives_at_budget(Y, BAD, 0.2) == 2


def test_compare_fp():
    out = compare_false_positives(Y, BAD, GOOD, [0.2])
    assert out.loc[0, "fp_before"] == 2 and out.loc[0, "fp_after"] == 0
    assert out.loc[0, "fp_reduction_pct"] == 100.0


def test_evaluate_keys():
    res = evaluate(Y, GOOD, [0.2])
    assert {"pr_auc", "roc_auc", "precision@0.2", "recall@0.2", "fp@0.2"} <= set(res)
