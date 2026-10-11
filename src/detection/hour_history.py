"""Entity hour-of-day history for the temporal layer (past-only, shrunk toward the global hours)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def past_hour_counts(keys: np.ndarray, hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Batch: for each row, earlier rows of the same entity at the same hour, and in total.

    Rows must be in time order; the current and later rows are never counted.
    """
    frame = pd.DataFrame({"k": keys, "h": hours})
    same_hour = frame.groupby(["k", "h"], sort=False).cumcount().to_numpy()
    total = frame.groupby("k", sort=False).cumcount().to_numpy()
    return same_hour.astype("float64"), total.astype("float64")


def hour_rarity(
    same_hour: np.ndarray, total: np.ndarray, global_share: np.ndarray, hours: np.ndarray, k: float
) -> np.ndarray:
    """-log10 of the shrunk probability of this hour: (c_h + k * g_h) / (n + k).

    Few past transactions -> the global hour share dominates (shrinkage).
    """
    p = (same_hour + k * global_share[hours]) / (total + k)
    return -np.log10(np.clip(p, 1e-12, 1.0))


class HourStore:
    """Online state: per-entity hour counts after the last processed row."""

    def __init__(self, hours_per_day: int) -> None:
        self.hours_per_day = hours_per_day
        self.counts: dict[str, np.ndarray] = {}

    @classmethod
    def from_arrays(cls, keys: np.ndarray, hours: np.ndarray, hours_per_day: int) -> HourStore:
        """Build the store from all rows seen so far."""
        store = cls(hours_per_day)
        frame = pd.DataFrame({"k": keys, "h": hours})
        table = frame.groupby(["k", "h"]).size().unstack(fill_value=0)
        table = table.reindex(columns=range(hours_per_day), fill_value=0)
        store.counts = {k: row for k, row in zip(table.index, table.to_numpy(), strict=True)}
        return store

    def lookup(self, keys: np.ndarray, hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Online: counts at the row's hour and in total for each key (unknown key = 0, 0)."""
        same_hour = np.zeros(len(keys))
        total = np.zeros(len(keys))
        for i, (key, hour) in enumerate(zip(keys, hours, strict=True)):
            row = self.counts.get(key)
            if row is not None:
                same_hour[i], total[i] = row[hour], row.sum()
        return same_hour, total

    def update(self, key: str, hour: int) -> None:
        """Record one processed transaction (not used by scoring; for a live service)."""
        row = self.counts.setdefault(key, np.zeros(self.hours_per_day, dtype="int64"))
        row[hour] += 1
