"""Robust preprocessing for multivariate input (K-11).

Order: -1 sentinel -> NaN; signed log on columns with |skew| above a threshold; clip to the fit
p0.1 / p99.9; NaN -> fit median plus a missing flag. All statistics come from the fit set.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def signed_log(x: np.ndarray) -> np.ndarray:
    """sign(x) * log1p(|x|)."""
    return np.sign(x) * np.log1p(np.abs(x))


class RobustPreprocessor:
    """Fit-set outlier handling and imputation for tree models."""

    def __init__(self, columns: list[str], sentinel_cols: list[str], cfg: dict[str, Any]) -> None:
        self.columns = list(columns)
        self.sentinel_cols = [c for c in sentinel_cols if c in self.columns]
        self.skew_threshold = float(cfg["skew_threshold"])
        self.clip_q = tuple(float(q) for q in cfg["clip_quantiles"])
        self.na_min_rate = float(cfg["na_flag_min_rate"])
        self.log_cols: list[str] = []
        self.bounds_: dict[str, tuple[float, float]] = {}
        self.medians_: dict[str, float] = {}
        self.na_cols: list[str] = []

    @property
    def output_columns(self) -> list[str]:
        """Names of the produced matrix columns (values, then missing flags)."""
        return self.columns + [f"{c}__na" for c in self.na_cols]

    def _column(self, df: pd.DataFrame, col: str) -> np.ndarray:
        """Column as float64 with sentinel -1 turned into NaN (absent column = all NaN)."""
        if col not in df.columns:
            return np.full(len(df), np.nan)
        x = df[col].to_numpy(dtype="float64", na_value=np.nan)
        if col in self.sentinel_cols:
            x = np.where(x == -1.0, np.nan, x)
        return x

    def fit(self, df: pd.DataFrame) -> RobustPreprocessor:
        """Learn skew decisions, clip bounds, medians and missing-flag columns."""
        self.log_cols, self.na_cols = [], []
        self.bounds_, self.medians_ = {}, {}
        for col in self.columns:
            x = self._column(df, col)
            na_rate = float(np.isnan(x).mean())
            if na_rate > self.na_min_rate:
                self.na_cols.append(col)
            ok = x[~np.isnan(x)]
            if len(ok) == 0:
                self.bounds_[col], self.medians_[col] = (0.0, 0.0), 0.0
                continue
            skew = pd.Series(ok).skew()
            if np.isfinite(skew) and abs(skew) > self.skew_threshold:
                self.log_cols.append(col)
                ok = signed_log(ok)
            lo, hi = np.quantile(ok, self.clip_q)
            self.bounds_[col] = (float(lo), float(hi))
            self.medians_[col] = float(np.median(np.clip(ok, lo, hi)))
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Return a float32 matrix (rows x output_columns); never contains NaN."""
        out = np.empty((len(df), len(self.output_columns)), dtype="float32")
        for j, col in enumerate(self.columns):
            x = self._column(df, col)
            na = np.isnan(x)
            if col in self.log_cols:
                x = signed_log(x)
            lo, hi = self.bounds_[col]
            out[:, j] = np.where(na, self.medians_[col], np.clip(x, lo, hi))
            if col in self.na_cols:
                out[:, len(self.columns) + self.na_cols.index(col)] = na
        return out
