"""Tail-probability scoring from a fit-set empirical distribution.

Score s = -log10(p), p = tail probability of the value under the fit distribution.
Modes: "two" (two-sided ECDF, p = 2 * min(F, 1 - F)), "upper", "lower", and "discrete"
(p = frequency of the value, for binary / few-valued columns). A +1 smoothing keeps p > 0
for values outside the fit range. Everything is learned on the fit set only.
"""

from __future__ import annotations

import numpy as np

MODES = ("two", "upper", "lower", "discrete")
NAN_POLICIES = ("level", "zero")


class TailScorer:
    """Empirical tail-probability scorer for one column."""

    def __init__(self, mode: str = "two", nan_policy: str = "level") -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
        if nan_policy not in NAN_POLICIES:
            raise ValueError(f"unknown nan_policy {nan_policy}")
        self.mode = mode
        self.nan_policy = nan_policy
        self.sorted_ = np.empty(0)
        self.uniq_ = np.empty(0)
        self.counts_ = np.empty(0)
        self.n_total_ = 0
        self.na_count_ = 0

    @property
    def n_(self) -> int:
        """Number of non-missing fit values."""
        return len(self.sorted_)

    def fit(self, values: np.ndarray) -> TailScorer:
        """Learn the distribution from fit-set values (NaN allowed)."""
        x = np.asarray(values, dtype="float64")
        ok = x[~np.isnan(x)]
        self.n_total_ = len(x)
        self.na_count_ = len(x) - len(ok)
        self.sorted_ = np.sort(ok)
        if self.mode == "discrete":
            self.uniq_, self.counts_ = np.unique(self.sorted_, return_counts=True)
        return self

    def n_unique(self) -> int:
        """Number of distinct non-missing fit values."""
        return len(np.unique(self.sorted_))

    def _probability(self, x: np.ndarray) -> np.ndarray:
        """Tail probability for non-missing values."""
        n = self.n_
        if self.mode == "discrete":
            idx = np.clip(np.searchsorted(self.uniq_, x), 0, len(self.uniq_) - 1)
            found = self.uniq_[idx] == x
            return np.where(found, self.counts_[idx] / n, 1.0 / (n + 1))
        le = np.searchsorted(self.sorted_, x, side="right")
        ge = n - np.searchsorted(self.sorted_, x, side="left")
        if self.mode == "upper":
            p = (ge + 1) / (n + 1)
        elif self.mode == "lower":
            p = (le + 1) / (n + 1)
        else:
            p = 2.0 * (np.minimum(le, ge) + 1) / (n + 1)
        return np.minimum(p, 1.0)

    def score(self, values: np.ndarray) -> np.ndarray:
        """Return -log10(tail probability) per value (float64, >= 0)."""
        x = np.asarray(values, dtype="float64")
        out = np.zeros(len(x))
        if self.n_ == 0:
            return out
        nan = np.isnan(x)
        out[~nan] = -np.log10(self._probability(x[~nan]))
        if self.nan_policy == "level" and nan.any():
            rate = self.na_count_ / self.n_total_ if self.na_count_ else 1.0 / (self.n_total_ + 1)
            out[nan] = -np.log10(rate)
        return out
