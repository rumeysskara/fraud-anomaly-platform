"""Fraud-rate-by-group tests on a synthetic label."""

import numpy as np
import pandas as pd

from src.evaluation.fraud_rate import fit_base_rate, fraud_rate_by, wilson_interval


def test_fraud_rate_by_counts_and_small_n():
    y = pd.Series([1, 0, 0, 0, 1, 1, 0, 0, 0, 0])
    g = pd.Series(pd.Categorical(list("aaaabbbbbb"), ["b", "a"], ordered=True))
    out = fraud_rate_by(y, g, min_n=5)
    assert list(out["group"]) == ["b", "a"]  # category order is kept
    assert list(out["n"]) == [6, 4]
    assert list(out["n_fraud"]) == [2, 1]
    assert out.loc[0, "fraud_rate"] == 2 / 6
    assert list(out["small_n"]) == [False, True]
    assert (out["ci_low"] <= out["fraud_rate"]).all() and (
        out["fraud_rate"] <= out["ci_high"]
    ).all()


def test_wilson_interval_zero_positives():
    low, high = wilson_interval(np.array([0]), np.array([30]))
    assert low[0] == 0 or abs(low[0]) < 1e-12
    assert 0.05 < high[0] < 0.2


def test_fit_base_rate():
    out = fit_base_rate(pd.Series([0, 1, 0, 0]))
    assert out == {"n": 4.0, "n_fraud": 1.0, "base_rate": 0.25}
