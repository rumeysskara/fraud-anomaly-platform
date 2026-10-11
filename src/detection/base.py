"""Shared base class of the four layer detectors."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

import numpy as np
import pandas as pd

from src.core.interfaces import Detector
from src.detection.normalization import QuantileNormalizer


def row_frame(row: pd.Series) -> pd.DataFrame:
    """One-row DataFrame from a record (the online path reuses the batch code)."""
    return pd.DataFrame([row.to_dict()], index=[row.name if row.name is not None else 0])


class LayerDetector(Detector):
    """Detector with a raw score and a fit-quantile normalizer.

    Subclasses implement `_fit_stats` (learn from the fit set), `raw_score` (unbounded layer
    score, higher = more anomalous) and `explain`. `score` returns the normalized [0,1] score.
    """

    name: str = "layer"

    def __init__(self, grid_points: int) -> None:
        self.grid_points = grid_points
        self.normalizer = QuantileNormalizer(grid_points)

    @abstractmethod
    def _fit_stats(self, df: pd.DataFrame) -> None:
        """Learn statistics / models from the fit set."""

    @abstractmethod
    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        """Unbounded raw layer score per row."""

    def raw_score_online(self, df: pd.DataFrame) -> np.ndarray:
        """Raw score on the API path (layers with online state override this)."""
        return self.raw_score(df)

    def fit(self, df: pd.DataFrame) -> LayerDetector:
        """Fit statistics, then the normalizer on the fit raw scores."""
        self._fit_stats(df)
        self.normalizer = QuantileNormalizer(self.grid_points).fit(self.raw_score(df))
        return self

    def score(self, df: pd.DataFrame) -> pd.Series:
        """Normalized layer score in [0,1], indexed like df."""
        return pd.Series(
            self.normalizer.transform(self.raw_score(df)), index=df.index, name=f"{self.name}_score"
        )

    def explain(self, row: pd.Series) -> dict[str, Any]:
        """Explain the score of one record."""
        frame = row_frame(row)
        out = self._explain_frame(frame)
        out["raw_score"] = float(self.raw_score(frame)[0])
        out["score"] = float(self.normalizer.transform(np.array([out["raw_score"]]))[0])
        return out

    @abstractmethod
    def _explain_frame(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Layer-specific explanation of a one-row frame."""
