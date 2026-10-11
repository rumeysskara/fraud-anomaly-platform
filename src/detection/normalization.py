"""Quantile-table score normalization (K-16): fit raw score -> [0,1] via np.interp."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.interfaces import Normalizer


class QuantileNormalizer(Normalizer):
    """Maps raw scores to [0,1] with a quantile table learned on the fit scores.

    The table has `grid_points` quantile levels; equal raw values (ties) share the mean of
    their levels (mean rank). The same table is used in batch and online scoring.
    """

    def __init__(self, grid_points: int = 1001) -> None:
        self.grid_points = grid_points
        self.xp_ = np.array([0.0])
        self.fp_ = np.array([0.5])
        self.table_ = pd.DataFrame({"level": [0.5], "raw_value": [0.0]})

    def fit(self, raw: np.ndarray) -> QuantileNormalizer:
        """Learn the table from fit-set raw scores."""
        x = np.asarray(raw, dtype="float64")
        x = x[~np.isnan(x)]
        levels = np.linspace(0.0, 1.0, self.grid_points)
        values = np.quantile(x, levels) if len(x) else np.zeros(self.grid_points)
        self.table_ = pd.DataFrame({"level": levels, "raw_value": values})
        grouped = self.table_.groupby("raw_value", sort=True)["level"].mean()
        self.xp_ = grouped.index.to_numpy(dtype="float64")
        self.fp_ = grouped.to_numpy(dtype="float64")
        return self

    def transform(self, raw: np.ndarray) -> np.ndarray:
        """Return normalized scores in [0,1] (NaN -> 0)."""
        x = np.nan_to_num(np.asarray(raw, dtype="float64"), nan=float(self.xp_[0]))
        return np.clip(np.interp(x, self.xp_, self.fp_), 0.0, 1.0)
