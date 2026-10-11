"""Column anomaly layer: per-column ECDF tail scores, row = mean of the top-k columns (K-12)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.detection.base import LayerDetector
from src.detection.tails import TailScorer


class ColumnDetector(LayerDetector):
    """Single-column anomalies on a curated explainable subset (no V columns)."""

    name = "column"

    def __init__(
        self,
        columns: list[str],
        top_k: int,
        discrete_max_unique: int,
        sentinel_cols: list[str],
        grid_points: int,
    ) -> None:
        super().__init__(grid_points)
        if len(columns) < top_k:
            raise ValueError("need at least top_k columns")
        self.columns = list(columns)
        self.top_k = top_k
        self.discrete_max_unique = discrete_max_unique
        self.sentinel_cols = [c for c in sentinel_cols if c in self.columns]
        self.scorers: dict[str, TailScorer] = {}

    def _values(self, df: pd.DataFrame, col: str) -> np.ndarray:
        """Column as float64; the -1 sentinel becomes NaN."""
        if col not in df.columns:
            return np.full(len(df), np.nan)
        x = df[col].to_numpy(dtype="float64", na_value=np.nan)
        return np.where(x == -1.0, np.nan, x) if col in self.sentinel_cols else x

    def _fit_stats(self, df: pd.DataFrame) -> None:
        """Fit one TailScorer per column; few-valued columns use -log frequency."""
        for col in self.columns:
            x = self._values(df, col)
            probe = TailScorer("two").fit(x)
            mode = "discrete" if probe.n_unique() <= self.discrete_max_unique else "two"
            self.scorers[col] = TailScorer(mode, "level").fit(x)

    def column_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Per-column tail scores (-log10 p), one column per input column."""
        data = {c: self.scorers[c].score(self._values(df, c)) for c in self.columns}
        return pd.DataFrame(data, index=df.index)

    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        """Mean of the top_k highest column scores per row."""
        s = self.column_scores(df).to_numpy()
        k = self.top_k
        return np.partition(s, s.shape[1] - k, axis=1)[:, -k:].mean(axis=1)

    def _explain_frame(self, frame: pd.DataFrame) -> dict[str, Any]:
        scores = self.column_scores(frame).iloc[0].sort_values(ascending=False)
        top = [
            {
                "column": c,
                "value": None if pd.isna(frame.iloc[0].get(c)) else float(frame.iloc[0][c]),
                "tail_score": round(float(v), 3),
                "mode": self.scorers[c].mode,
            }
            for c, v in scores.head(self.top_k).items()
        ]
        return {"layer": self.name, "top_columns": top}
