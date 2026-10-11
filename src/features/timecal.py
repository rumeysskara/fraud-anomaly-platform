"""Calendar features: hour, weekday, low-volume window, local-time estimate, US holidays.

ASSUMPTIONS (documented in docs/step3.md): datetime = reference_date + TransactionDT seconds;
the reference clock is not a known time zone, so the local hour is estimated by assuming the
fit low-volume window is local 00:00-06:00. Holidays are matched on the reference-clock date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CalendarSpec:
    """Constants for calendar features (all read from configs)."""

    ref_seconds: int
    holiday_days: np.ndarray  # sorted epoch days
    low_volume_length: int
    business_start: int
    business_end: int

    @classmethod
    def from_config(
        cls, reference_date: str, features_cfg: dict, holidays: list[date]
    ) -> CalendarSpec:
        """Build from settings (reference date) and entity.yaml `features` + holidays file."""
        days = np.array(sorted((pd.Timestamp(d) - pd.Timestamp(0)).days for d in holidays))
        return cls(
            ref_seconds=int(pd.Timestamp(reference_date).timestamp()),
            holiday_days=days.astype("int64"),
            low_volume_length=int(features_cfg["low_volume"]["length_hours"]),
            business_start=int(features_cfg["local_time"]["business_start_hour"]),
            business_end=int(features_cfg["local_time"]["business_end_hour"]),
        )


def hourly_counts(dt: np.ndarray, ref_seconds: int) -> np.ndarray:
    """Row count per reference-clock hour of day (length 24)."""
    hours = ((ref_seconds + dt) // 3600) % 24
    return np.bincount(hours.astype("int64"), minlength=24)


def lowest_window_start(counts: np.ndarray, length: int) -> int:
    """Start hour of the consecutive `length` hours (circular) with the lowest total volume."""
    sums = [sum(counts[(s + k) % 24] for k in range(length)) for s in range(24)]
    return int(np.argmin(sums))


def calendar_features(
    dt: np.ndarray,
    spec: CalendarSpec,
    low_volume_start: int,
    local_offset_hours: int,
    season: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Temporal + holiday features from TransactionDT seconds (vectorised, pure).

    season = (start_epoch_day, end_epoch_day) inclusive, learned on the fit set
    (detect_season); None means no season was found.
    """
    dt = np.asarray(dt, dtype="int64")
    t = spec.ref_seconds + dt
    hour = (t // 3600) % 24
    dow = ((t // 86400) + 3) % 7  # 1970-01-01 was a Thursday (Monday = 0)
    local_t = t + local_offset_hours * 3600
    local_hour = (local_t // 3600) % 24
    local_dow = ((local_t // 86400) + 3) % 7
    rel = (hour - low_volume_start) % 24

    days = t // 86400
    if len(spec.holiday_days):
        pos = np.searchsorted(spec.holiday_days, days)
        left = spec.holiday_days[np.clip(pos - 1, 0, len(spec.holiday_days) - 1)]
        right = spec.holiday_days[np.clip(pos, 0, len(spec.holiday_days) - 1)]
        nearest = np.minimum(np.abs(days - left), np.abs(days - right))
        is_holiday = np.isin(days, spec.holiday_days)
    else:
        nearest = np.full(len(days), 999)
        is_holiday = np.zeros(len(days), dtype=bool)
    in_season = (days >= season[0]) & (days <= season[1]) if season else np.zeros(len(days), bool)

    return pd.DataFrame(
        {
            "hour": hour,
            "day_of_week": dow,
            "is_weekend": dow >= 5,
            "day_index": dt // 86400,
            "is_low_volume_window": rel < spec.low_volume_length,
            "local_hour_est": local_hour,
            "is_business_hours": (local_hour >= spec.business_start)
            & (local_hour < spec.business_end)
            & (local_dow < 5),
            "is_holiday": is_holiday,
            "holiday_season": in_season,
            "days_to_nearest_holiday": nearest,
        }
    )


def daily_ratio(dt: np.ndarray, ref_seconds: int, baseline_days: int) -> pd.DataFrame:
    """Daily volume and its ratio to the centered rolling median of `baseline_days` days.

    Days are reference-clock calendar days (epoch day). The last day is dropped because the
    fit set is cut by row count, so it is usually incomplete.
    """
    days = (ref_seconds + np.asarray(dt, dtype="int64")) // 86400
    counts = pd.Series(days).value_counts().sort_index()
    counts = counts.reindex(
        range(int(counts.index.min()), int(counts.index.max()) + 1), fill_value=0
    )
    counts = counts.iloc[:-1]
    base = counts.rolling(
        baseline_days, center=True, min_periods=max(3, baseline_days // 3)
    ).median()
    return pd.DataFrame({"count": counts, "baseline": base, "ratio": counts / base})


def detect_season(dt: np.ndarray, ref_seconds: int, cfg: dict) -> tuple[dict | None, pd.DataFrame]:
    """Find the season window from FIT volume only (no label).

    Rule: ratio_d = daily volume / centered median of the surrounding `baseline_days` days.
    Days with ratio_d >= ratio_threshold form blocks of consecutive days; blocks shorter than
    `min_days` are ignored (single-day spikes); the block with the largest sum of (ratio_d - 1)
    is the season. Returns (window or None, daily table with an `in_window` column).
    """
    table = daily_ratio(dt, ref_seconds, cfg["baseline_days"])
    high = (table["ratio"] >= cfg["ratio_threshold"]).to_numpy()
    days = table.index.to_numpy()
    best, i = None, 0
    while i < len(high):
        if not high[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(high) and high[j + 1] and days[j + 1] == days[j] + 1:
            j += 1
        block = table["ratio"].iloc[i : j + 1]
        if len(block) >= cfg["min_days"] and (best is None or (block - 1).sum() > best["excess"]):
            best = {
                "start_day": int(days[i]),
                "end_day": int(days[j]),
                "n_days": int(len(block)),
                "mean_ratio": float(block.mean()),
                "excess": float((block - 1).sum()),
            }
        i = j + 1
    table["in_window"] = False
    if best:
        table.loc[best["start_day"] : best["end_day"], "in_window"] = True
    return best, table


def epoch_day_to_date(day: int) -> str:
    """ISO date of an epoch day (reference-clock calendar)."""
    return str((pd.Timestamp(0) + pd.Timedelta(days=int(day))).date())
