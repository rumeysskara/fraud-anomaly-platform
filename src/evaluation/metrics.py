"""Evaluation metrics. Together with the loader, the only place that reads isFraud."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def pr_auc(y: pd.Series, score: pd.Series) -> float:
    """Area under the precision-recall curve (average precision)."""
    return float(average_precision_score(y, score.loc[y.index]))


def roc_auc(y: pd.Series, score: pd.Series) -> float:
    """Area under the ROC curve."""
    return float(roc_auc_score(y, score.loc[y.index]))


def _top_k_index(score: pd.Series, k: int) -> pd.Index:
    """Index of the k highest scores (stable, ties broken by order)."""
    order = np.argsort(-score.to_numpy(), kind="stable")[:k]
    return score.index[order]


def precision_at_k(y: pd.Series, score: pd.Series, k: int) -> float:
    """Fraction of the top-k scored rows that are positive."""
    top = _top_k_index(score.loc[y.index], k)
    return float(y.loc[top].sum() / max(len(top), 1))


def recall_at_k(y: pd.Series, score: pd.Series, k: int) -> float:
    """Fraction of all positives caught in the top-k scored rows."""
    total = int(y.sum())
    if total == 0:
        return 0.0
    top = _top_k_index(score.loc[y.index], k)
    return float(y.loc[top].sum() / total)


def false_positives_at_budget(y: pd.Series, score: pd.Series, budget: float) -> int:
    """Number of non-fraud rows among the top `budget` fraction of scores."""
    k = math.ceil(budget * len(y))
    top = _top_k_index(score.loc[y.index], k)
    return int((y.loc[top] == 0).sum())


def compare_false_positives(
    y: pd.Series, before: pd.Series, after: pd.Series, budgets: list[float]
) -> pd.DataFrame:
    """Before/after false positive counts at each alarm budget (e.g. before/after context)."""
    rows = []
    for b in budgets:
        fp_b = false_positives_at_budget(y, before, b)
        fp_a = false_positives_at_budget(y, after, b)
        rows.append(
            {
                "budget": b,
                "fp_before": fp_b,
                "fp_after": fp_a,
                "fp_change": fp_a - fp_b,
                "fp_reduction_pct": 100.0 * (fp_b - fp_a) / fp_b if fp_b else 0.0,
            }
        )
    return pd.DataFrame(rows)


def evaluate(y: pd.Series, score: pd.Series, budgets: list[float]) -> dict[str, float]:
    """Standard report: PR-AUC, ROC-AUC, precision@k and recall@k per budget."""
    out = {"pr_auc": pr_auc(y, score), "roc_auc": roc_auc(y, score)}
    for b in budgets:
        k = math.ceil(b * len(y))
        out[f"precision@{b}"] = precision_at_k(y, score, k)
        out[f"recall@{b}"] = recall_at_k(y, score, k)
        out[f"fp@{b}"] = false_positives_at_budget(y, score, b)
    return out
