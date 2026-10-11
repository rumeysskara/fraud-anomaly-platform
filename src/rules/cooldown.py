"""Per-entity rule cooldown: a rule fires at most once per entity within a time window.

Past-only: whether a row's hit is kept depends only on the entity's EARLIER kept hits. Batch and
online share apply_cooldown:
- batch: rows are processed in TransactionDT order with a fresh state (fit + holdout, like the
  Step 3 history features);
- online: the state is a CooldownStore (last fire time per rule and entity) injected into the
  engine. It is stateful (in memory, one process); a multi-process API would need a shared store.
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
) -> np.ndarray:
    """Keep a hit only if the entity's previous KEPT hit is at least window_seconds earlier.

    Rows are visited in time order (stable). last_fired (key -> time of the last kept hit) is
    read and updated in place, so the same state can carry over to later calls.
    """
    kept = hit.copy()
    rows = np.flatnonzero(hit)
    for i in rows[np.argsort(times[rows], kind="stable")]:
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
    """Online state: last fire time per (rule id, entity key). In memory, single process."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, float]] = {}

    def for_rule(self, rule_id: str) -> dict[str, float]:
        """Mutable key -> last fire time map of one rule."""
        return self._state.setdefault(rule_id, {})

    def set(self, rule_id: str, key: str, time: float) -> None:
        """Record a fire time (used to seed the state, e.g. from a batch replay)."""
        self.for_rule(rule_id)[key] = float(time)

    def copy(self) -> CooldownStore:
        """Independent copy (read-only evaluation)."""
        other = CooldownStore()
        other._state = {rid: dict(m) for rid, m in self._state.items()}
        return other

    def clear(self) -> None:
        """Forget all state."""
        self._state.clear()
