"""Score aggregation strategies (Strategy pattern).

Main method: weighted average with configs/weights.yaml (K-17). The others (max, noisy-OR,
correlation-weighted) exist for the ablation / comparison table only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.interfaces import Aggregator


def _frame(scores: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame(scores)


class WeightedAverage(Aggregator):
    """raw_score = sum(w_i * s_i) with weights renormalized over the layers present."""

    def __init__(self, weights: dict[str, float]) -> None:
        self.weights = dict(weights)

    def effective_weights(self, layers: list[str]) -> dict[str, float]:
        """Weights restricted to `layers` and renormalized to sum 1."""
        w = {k: self.weights[k] for k in layers if k in self.weights}
        total = sum(w.values())
        if total <= 0:
            raise ValueError("no weight for the given layers")
        return {k: v / total for k, v in w.items()}

    def contributions(self, scores: dict[str, pd.Series]) -> pd.DataFrame:
        """w_i * s_i per layer (columns contrib_<layer>); their row sum is the aggregate."""
        w = self.effective_weights(list(scores))
        return pd.DataFrame({f"contrib_{k}": w[k] * scores[k] for k in w})

    def aggregate(self, scores: dict[str, pd.Series]) -> pd.Series:
        """Weighted average in [0,1]."""
        return self.contributions(scores).sum(axis=1).clip(0.0, 1.0).rename("raw_anomaly_score")


class MaxAggregator(Aggregator):
    """The highest layer score (sensitive to a single noisy layer)."""

    def aggregate(self, scores: dict[str, pd.Series]) -> pd.Series:
        """Row-wise maximum."""
        return _frame(scores).max(axis=1)


class NoisyOrAggregator(Aggregator):
    """1 - prod(1 - s_i): independent evidence combination (saturates quickly)."""

    def aggregate(self, scores: dict[str, pd.Series]) -> pd.Series:
        """Noisy-OR of the layer scores."""
        return 1.0 - (1.0 - _frame(scores)).prod(axis=1)


class CorrelationWeighted(WeightedAverage):
    """Weights proportional to 1 / mean |corr| with the other layers (label-free, fit scores).

    A layer that is highly correlated with the others adds little new information and gets less
    weight. Weights are learned on the fit set only.
    """

    def __init__(self) -> None:
        super().__init__({})

    def fit(self, scores: dict[str, pd.Series]) -> CorrelationWeighted:
        """Learn weights from the fit-set layer scores (Spearman correlation)."""
        corr = _frame(scores).corr(method="spearman").abs()
        n = len(corr)
        mean_other = (corr.sum(axis=0) - 1.0) / max(n - 1, 1)
        inv = 1.0 / mean_other.clip(lower=1e-6)
        self.weights = (inv / inv.sum()).to_dict()
        return self


def rank_check(values: pd.Series) -> bool:
    """True when all values are finite and in [0,1] (used by tests and the pipeline)."""
    v = values.to_numpy()
    return bool(np.isfinite(v).all() and v.min() >= 0.0 and v.max() <= 1.0)
