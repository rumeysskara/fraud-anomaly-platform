"""Temporal anomaly layer: rule-based sub-scores averaged with config weights (K-15).

Sub-scores (all -log10 p units, learned on the fit set):
  velocity           upper tail of windowed counts / sums (max over the configured columns)
  inter_arrival      lower tail of time since last txn, and of that time relative to the entity's
                     mean inter-arrival (max of the two)
  low_volume_window  -log frequency of the low-volume-window flag
  hour_rarity        rarity of the hour for this entity (shrunk toward the global hours), upper tail
  baseline_volume    (day-of-week, hour) cell with lower fit volume than average
The baseline term is stateless (fit share of the cell), so batch and online are identical.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.detection.aux import ENTITY_KEY
from src.detection.base import LayerDetector
from src.detection.hour_history import HourStore, hour_rarity, past_hour_counts
from src.detection.tails import TailScorer

SUBSCORES = ("velocity", "inter_arrival", "low_volume_window", "hour_rarity", "baseline_volume")


def _num(df: pd.DataFrame, col: str) -> np.ndarray:
    """Column as float64 (absent column = NaN)."""
    if col not in df.columns:
        return np.full(len(df), np.nan)
    return df[col].to_numpy(dtype="float64", na_value=np.nan)


class TemporalDetector(LayerDetector):
    """Velocity, inter-arrival, low-volume, entity-hour and calendar-volume sub-scores."""

    name = "temporal"

    def __init__(self, cfg: dict[str, Any], sentinel_cols: list[str], grid_points: int) -> None:
        super().__init__(grid_points)
        weights = {k: float(cfg["subscore_weights"][k]) for k in SUBSCORES}
        total = sum(weights.values())
        self.weights = {k: v / total for k, v in weights.items()}
        self.velocity_columns = list(cfg["velocity_columns"])
        self.k = float(cfg["hour_shrinkage_k"])
        self.hours = int(cfg["hours_per_day"])
        self.days = int(cfg["days_per_week"])
        self.sentinel_cols = list(sentinel_cols)
        self.scorers: dict[str, TailScorer] = {}
        self.global_hour_share_ = np.full(self.hours, 1.0 / self.hours)
        self.cell_share_ = np.full(self.hours * self.days, 1.0 / (self.hours * self.days))
        self.store: HourStore | None = None

    def _col(self, df: pd.DataFrame, col: str) -> np.ndarray:
        """Column as float64; the -1 sentinel becomes NaN."""
        x = _num(df, col)
        return np.where(x == -1.0, np.nan, x) if col in self.sentinel_cols else x

    def _keys_hours(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        hours = np.nan_to_num(_num(df, "hour"), nan=0.0).astype(int) % self.hours
        if ENTITY_KEY in df.columns:
            keys = df[ENTITY_KEY].to_numpy()
        else:
            keys = np.arange(len(df)).astype(str)  # no key: every row is a new entity
        return keys, hours

    def _rarity(self, df: pd.DataFrame, online: bool) -> np.ndarray:
        keys, hours = self._keys_hours(df)
        if online and self.store is not None:
            same, total = self.store.lookup(keys, hours)
        else:
            same, total = past_hour_counts(keys, hours)
        return hour_rarity(same, total, self.global_hour_share_, hours, self.k)

    def _ratio(self, df: pd.DataFrame) -> np.ndarray:
        """Time since last txn relative to the entity's mean inter-arrival (NaN if undefined)."""
        gap, mean_gap = self._col(df, "time_since_last_txn"), self._col(df, "avg_inter_arrival")
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(mean_gap > 0, gap / mean_gap, np.nan)

    def _cell(self, df: pd.DataFrame) -> np.ndarray:
        _, hours = self._keys_hours(df)
        dow = np.nan_to_num(_num(df, "day_of_week"), nan=0.0).astype(int) % self.days
        return dow * self.hours + hours

    def _fit_stats(self, df: pd.DataFrame) -> None:
        """Learn tail distributions, global hour shares and calendar-cell shares."""
        sc = self.scorers
        for col in self.velocity_columns:
            sc[col] = TailScorer("upper", "zero").fit(self._col(df, col))
        sc["gap"] = TailScorer("lower", "zero").fit(self._col(df, "time_since_last_txn"))
        sc["ratio"] = TailScorer("lower", "zero").fit(self._ratio(df))
        sc["low_volume"] = TailScorer("discrete", "zero").fit(_num(df, "is_low_volume_window"))
        _, hours = self._keys_hours(df)
        counts = np.bincount(hours, minlength=self.hours) + 1.0
        self.global_hour_share_ = counts / counts.sum()
        cells = np.bincount(self._cell(df), minlength=self.hours * self.days) + 1.0
        self.cell_share_ = cells / cells.sum()
        sc["hour_rarity"] = TailScorer("upper", "zero").fit(self._rarity(df, online=False))

    def subscores(self, df: pd.DataFrame, online: bool = False) -> pd.DataFrame:
        """The five sub-scores per row (-log10 p units)."""
        sc = self.scorers
        velocity = np.max([sc[c].score(self._col(df, c)) for c in self.velocity_columns], axis=0)
        gap_score = sc["gap"].score(self._col(df, "time_since_last_txn"))
        inter = np.maximum(gap_score, sc["ratio"].score(self._ratio(df)))
        cell_share = self.cell_share_[self._cell(df)]
        baseline = np.maximum(0.0, -np.log10(cell_share * len(self.cell_share_)))
        data = {
            "velocity": velocity,
            "inter_arrival": inter,
            "low_volume_window": sc["low_volume"].score(_num(df, "is_low_volume_window")),
            "hour_rarity": sc["hour_rarity"].score(self._rarity(df, online)),
            "baseline_volume": baseline,
        }
        return pd.DataFrame(data, index=df.index)

    def _combine(self, sub: pd.DataFrame) -> np.ndarray:
        return sum(self.weights[k] * sub[k].to_numpy() for k in SUBSCORES)

    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        """Weighted mean of the sub-scores (batch: expanding entity-hour history)."""
        return self._combine(self.subscores(df))

    def raw_score_online(self, df: pd.DataFrame) -> np.ndarray:
        """Same code, entity-hour history read from the persisted store."""
        return self._combine(self.subscores(df, online=True))

    def build_store(self, df: pd.DataFrame) -> HourStore:
        """Persist the hour counts of all rows seen so far (state for the API)."""
        keys, hours = self._keys_hours(df)
        self.store = HourStore.from_arrays(keys, hours, self.hours)
        return self.store

    def _explain_frame(self, frame: pd.DataFrame) -> dict[str, Any]:
        sub = self.subscores(frame, online=self.store is not None).iloc[0]
        return {
            "layer": self.name,
            "subscores": {k: round(float(sub[k]), 4) for k in SUBSCORES},
            "weights": self.weights,
            "top_subscore": str(sub.idxmax()),
        }
