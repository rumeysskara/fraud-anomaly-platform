"""Multivariate anomaly layer: Isolation Forest only (K-13)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from src.detection.base import LayerDetector
from src.detection.preprocess import RobustPreprocessor


class MultivariateDetector(LayerDetector):
    """Isolation Forest on robustly preprocessed features (signed log, clip, median + NaN flags)."""

    def __init__(
        self,
        name: str,
        columns: list[str],
        sentinel_cols: list[str],
        pre_cfg: dict[str, Any],
        if_cfg: dict[str, Any],
        seed: int,
        grid_points: int,
        explain_top: int = 5,
    ) -> None:
        super().__init__(grid_points)
        self.name = name
        self.columns = list(columns)
        self.pre = RobustPreprocessor(columns, sentinel_cols, pre_cfg)
        self.if_cfg = dict(if_cfg)
        self.seed = seed
        self.explain_top = explain_top
        self.model: IsolationForest | None = None

    def _fit_stats(self, df: pd.DataFrame) -> None:
        """Fit the preprocessor and the forest on the fit set."""
        self.pre.fit(df)
        self.model = IsolationForest(random_state=self.seed, **self.if_cfg)
        self.model.fit(self.pre.transform(df))

    def _raw_from_matrix(self, x: np.ndarray) -> np.ndarray:
        """Anomaly score of the forest: -score_samples, in (0,1), higher = more anomalous."""
        assert self.model is not None, "fit() first"
        return -self.model.score_samples(x)

    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        """Forest anomaly score per row."""
        return self._raw_from_matrix(self.pre.transform(df))

    def _explain_frame(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Leave-one-feature-out: replace a feature by its fit median and measure the drop."""
        x0 = self.pre.transform(frame)
        names = self.pre.output_columns
        n = len(self.columns)
        variants = np.repeat(x0, n + 1, axis=0)
        for j, col in enumerate(self.columns):
            variants[j + 1, j] = self.pre.medians_[col]
            if col in self.pre.na_cols:
                variants[j + 1, n + self.pre.na_cols.index(col)] = 0.0
        raw = self._raw_from_matrix(variants)
        drops = raw[0] - raw[1:]
        order = np.argsort(-drops)[: self.explain_top]
        top = [
            {
                "feature": self.columns[j],
                "value": float(x0[0, j]),
                "fit_median": self.pre.medians_[self.columns[j]],
                "contribution": round(float(drops[j]), 5),
            }
            for j in order
        ]
        return {"layer": self.name, "n_features": len(names), "top_features": top}
