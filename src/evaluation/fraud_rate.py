"""Descriptive fraud rate by group. Reads the label, so it lives in src/evaluation.

Callers pass only the fit part of y (never the holdout). Groups are built label-free elsewhere.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Z_95 = 1.959964  # standard normal quantile for a 95% interval


def wilson_interval(k: np.ndarray, n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """95% Wilson score interval for k positives out of n (vectorised, n >= 1)."""
    n = np.maximum(n, 1)
    p = k / n
    denom = 1 + Z_95**2 / n
    centre = (p + Z_95**2 / (2 * n)) / denom
    half = Z_95 * np.sqrt(p * (1 - p) / n + Z_95**2 / (4 * n**2)) / denom
    return centre - half, centre + half


def fraud_rate_by(y: pd.Series, groups: pd.Series, min_n: int) -> pd.DataFrame:
    """Fraud rate per group: n, n_fraud, fraud_rate, Wilson CI and a small_n flag (n < min_n).

    y and groups must share the same index. Group order follows the categories of `groups`
    when it is categorical, otherwise sorted order.
    """
    frame = pd.DataFrame({"y": y.to_numpy(), "group": groups.reset_index(drop=True)})
    agg = frame.groupby("group", observed=True, sort=True)["y"].agg(["size", "sum"])
    agg.columns = ["n", "n_fraud"]
    low, high = wilson_interval(agg["n_fraud"].to_numpy(), agg["n"].to_numpy())
    out = agg.reset_index()
    out["fraud_rate"] = out["n_fraud"] / out["n"]
    out["ci_low"], out["ci_high"] = low, high
    out["small_n"] = out["n"] < min_n
    return out


def fit_base_rate(y: pd.Series) -> dict[str, float]:
    """Row count, positives and base rate of a (fit) label Series."""
    return {"n": float(len(y)), "n_fraud": float(y.sum()), "base_rate": float(y.mean())}
