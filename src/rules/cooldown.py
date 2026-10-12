"""Per-entity rule cooldown: a rule fires at most once per entity within a time window.

Past-only: whether a row's hit is kept depends only on the entity's EARLIER kept hits. "Earlier"
is the order (TransactionDT, TransactionID): rows with the same TransactionDT are ordered by
TransactionID. Batch and online share apply_cooldown:
- batch: all rows (fit + holdout) in that order, starting from an empty state;
- online: the state comes from a CooldownStore injected into the engine (container Singleton).
  The store keeps the recent fires per (rule, entity) and the processed TransactionIDs, so the
  same transaction evaluated twice gets the same answer and updates the state only once.
  It lives in memory in one process (future work: a transaction-recording endpoint and a
  persistent store).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.utils import entity_keys


def apply_cooldown(
    hit: np.ndarray,
    times: np.ndarray,
    keys: np.ndarray,
    window_seconds: float,
    last_fired: dict[str, float],
    ids: np.ndarray | None = None,
) -> np.ndarray:
    """Keep a hit only if the entity's previous KEPT hit is at least window_seconds earlier.

    Rows are visited in (time, id) order (stable row order when ids is None). last_fired
    (key -> time of the last kept hit) is read and updated in place.
    """
    kept = hit.copy()
    rows = np.flatnonzero(hit)
    if ids is None:
        order = rows[np.argsort(times[rows], kind="stable")]
    else:
        order = rows[np.lexsort((ids[rows], times[rows]))]
    for i in order:
        key, t = keys[i], float(times[i])
        prev = last_fired.get(key)
        if prev is not None and t - prev < window_seconds:
            kept[i] = False
        else:
            last_fired[key] = t
    return kept


def cooldown_keys(df: pd.DataFrame, entity_columns: list[str]) -> np.ndarray:
    """Entity key per row (same key definition as Step 3, NaN is its own level)."""
    return entity_keys(df, entity_columns).to_numpy()


class CooldownStore:
    """Online cooldown state (in memory, one process).

    - fires: (rule id, entity key) -> list of (time, TransactionID) of kept fires
    - processed: TransactionID -> time; a processed transaction never updates the state again
    Entries older than the largest cooldown window (relative to the newest time seen) are
    dropped, so memory stays bounded by the traffic of one window.
    """

    def __init__(self) -> None:
        self._fires: dict[tuple[str, str], list[tuple[float, int]]] = {}
        self._processed: dict[int, float] = {}
        self._newest = float("-inf")

    def last_fire_before(self, rule_id: str, key: str, time: float, tid: int) -> float | None:
        """Time of the entity's last kept fire strictly before (time, tid), or None."""
        earlier = [t for t, i in self._fires.get((rule_id, key), []) if (t, i) < (time, tid)]
        return max(earlier) if earlier else None

    def is_processed(self, tid: int) -> bool:
        """True when this TransactionID already updated the state."""
        return tid in self._processed

    def add_fire(self, rule_id: str, key: str, time: float, tid: int) -> None:
        """Record a kept fire (also used to seed the state, e.g. from a batch replay)."""
        self._fires.setdefault((rule_id, key), []).append((float(time), int(tid)))

    def record(
        self, tid: int, time: float, fires: list[tuple[str, str]], window_seconds: float
    ) -> bool:
        """Record one transaction's kept fires once (idempotent); return True if written."""
        if self.is_processed(tid):
            return False
        self._processed[int(tid)] = float(time)
        for rule_id, key in fires:
            self.add_fire(rule_id, key, time, tid)
        self._newest = max(self._newest, float(time))
        self.prune(window_seconds)
        return True

    def prune(self, window_seconds: float) -> None:
        """Drop fires and processed ids older than newest time - window_seconds."""
        limit = self._newest - window_seconds
        self._processed = {i: t for i, t in self._processed.items() if t >= limit}
        fires = {}
        for k, items in self._fires.items():
            recent = [(t, i) for t, i in items if t >= limit]
            if recent:
                fires[k] = recent
        self._fires = fires

    def size(self) -> tuple[int, int]:
        """(number of stored fires, number of processed ids)."""
        return sum(len(v) for v in self._fires.values()), len(self._processed)

    def copy(self) -> CooldownStore:
        """Independent copy."""
        other = CooldownStore()
        other._fires = {k: list(v) for k, v in self._fires.items()}
        other._processed = dict(self._processed)
        other._newest = self._newest
        return other

    def clear(self) -> None:
        """Forget all state."""
        self._fires.clear()
        self._processed.clear()
        self._newest = float("-inf")
