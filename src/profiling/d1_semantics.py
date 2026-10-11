"""Test what D1 means, using the chosen entity (configs/entity.yaml). Label-free.

Hypothesis A: D1 = days since the previous transaction. Under A, for a row with an earlier
transaction in the same entity, floor(DT/day) gap to that transaction is close to D1.
Hypothesis B: D1 = days since the card started (card age). Under B, D1n = day - D1 is a
stable card attribute, so the pair (entity, D1n) repeats; permuting D1 inside the entity
breaks that, so the repeat rate must drop.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.profiling.config import entity_definition, profiling_config
from src.profiling.entity import entity_codes


def previous_day_gap(key: np.ndarray, day: np.ndarray) -> np.ndarray:
    """Day difference to the previous row of the same entity (NaN if there is none).

    Rows must be time-sorted; key < 0 (undefined) rows get NaN.
    """
    order = np.argsort(key, kind="stable")  # keeps time order inside each entity
    k, d = key[order], day[order]
    gap = np.full(len(key), np.nan)
    same = (k[1:] == k[:-1]) & (k[1:] >= 0)
    gap_sorted = np.full(len(key), np.nan)
    gap_sorted[1:][same] = d[1:][same] - d[:-1][same]
    gap[order] = gap_sorted
    return gap


def seen_before_rate(key: np.ndarray, start_day: np.ndarray, mask: np.ndarray) -> float:
    """Share of rows in mask whose (entity, start_day) pair occurred in an earlier row."""
    ok = (key >= 0) & ~np.isnan(start_day)
    pairs = pd.DataFrame({"k": key[ok], "d": start_day[ok]})
    seen = np.zeros(len(key), dtype=bool)
    seen[ok] = (pairs.groupby(["k", "d"], sort=False).cumcount() > 0).to_numpy()
    return float(seen[mask & ok].mean()) if (mask & ok).any() else float("nan")


def permute_within(key: np.ndarray, values: np.ndarray, seed: int) -> np.ndarray:
    """Shuffle values among the rows of each entity (seeded); other rows are unchanged."""
    rng = np.random.default_rng(seed)
    base = np.argsort(key, kind="stable")
    shuffled = np.lexsort((rng.random(len(key)), key))
    out = values.copy()
    out[base] = values[shuffled]
    return out


def d1_semantics(
    df: pd.DataFrame, time_col: str, seed: int, cfg: dict | None = None
) -> pd.DataFrame:
    """Long table (metric, value, n_rows, note) for hypotheses A and B on the chosen entity."""
    cfg = cfg or profiling_config("d1_semantics")
    tol = cfg["tolerance_days"]
    ent = entity_definition()
    d_col, secs = ent["card_start_day"]["d_column"], ent["card_start_day"]["day_seconds"]
    key = entity_codes(df, ent["columns"], ent.get("na_level"))
    day = np.floor(df[time_col].to_numpy("float64") / secs)
    d1 = df[d_col].to_numpy("float64")
    d1_perm = permute_within(key, d1, seed)

    gap = previous_day_gap(key, day)
    has_prev = ~np.isnan(gap) & ~np.isnan(d1)
    gap_perm_ok = np.abs(gap - d1_perm) <= tol
    rows = [
        {
            "metric": "A_prev_gap_matches_D1",
            "value": float((np.abs(gap - d1) <= tol)[has_prev].mean()),
            "n_rows": int(has_prev.sum()),
            "note": f"|gap to previous txn in entity (days) - D1| <= {tol}; rows without previous "
            "txn excluded",
        },
        {
            "metric": "A_prev_gap_matches_D1_permuted",
            "value": float(gap_perm_ok[has_prev].mean()),
            "n_rows": int(has_prev.sum()),
            "note": "same, with D1 shuffled inside the entity (chance level)",
        },
    ]
    d1n = day - d1
    d1n_perm = day - d1_perm
    defined = (key >= 0) & ~np.isnan(d1)
    with_prev = defined & ~np.isnan(gap)
    for label, mask in (("all_D1_rows", defined), ("rows_with_previous_txn", with_prev)):
        rows.append(
            {
                "metric": f"B_pair_seen_before[{label}]",
                "value": seen_before_rate(key, d1n, mask),
                "n_rows": int(mask.sum()),
                "note": "(entity, D1n) pair seen in an earlier row",
            }
        )
        rows.append(
            {
                "metric": f"B_pair_seen_before_permuted[{label}]",
                "value": seen_before_rate(key, d1n_perm, mask),
                "n_rows": int(mask.sum()),
                "note": f"same, D1 shuffled inside the entity (seed {seed})",
            }
        )
    return pd.DataFrame(rows)
