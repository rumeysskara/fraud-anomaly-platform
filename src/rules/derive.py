"""Derived rule features and the batch input builder. Batch and single records share add_derived.

All inputs are past-only (Step 3 history features + email_ent_known), so the derived columns are
past-only too:
- known_device   = the entity used this device before            (device_ent_match >= 1)
- known_email    = the entity used this P_emaildomain before      (email_ent_known == 1)
- ent_daily_avg  = ent_txn_count / max(ent_age_days, daily_avg_min_days)
- burst_ratio_1h = ent_cnt_1h / ent_daily_avg (NaN when the entity has no history)
"""

from __future__ import annotations

import pandas as pd

from src.context.derive import EMAIL_KNOWN
from src.context.inputs import RAW_SOURCE_COLUMNS, email_known_batch

# derived column -> input columns it needs
DERIVED_DEPS: dict[str, list[str]] = {
    "known_device": ["device_ent_match"],
    "known_email": [EMAIL_KNOWN],
    "ent_daily_avg": ["ent_txn_count", "ent_age_days"],
    "burst_ratio_1h": ["ent_cnt_1h", "ent_txn_count", "ent_age_days"],
}
DERIVED_COLUMNS = list(DERIVED_DEPS)


def add_derived(df: pd.DataFrame, daily_avg_min_days: float) -> pd.DataFrame:
    """Return a copy of df with the derived columns whose inputs are present."""
    out = df.copy()
    cols = set(out.columns)
    if "device_ent_match" in cols:
        out["known_device"] = (out["device_ent_match"].astype("float64") >= 1).astype("int8")
    if EMAIL_KNOWN in cols:
        out["known_email"] = (out[EMAIL_KNOWN].astype("float64") >= 1).astype("int8")
    if {"ent_txn_count", "ent_age_days"} <= cols:
        age = out["ent_age_days"].astype("float64").clip(lower=daily_avg_min_days)
        daily = out["ent_txn_count"].astype("float64") / age
        out["ent_daily_avg"] = daily
        if "ent_cnt_1h" in cols:
            ratio = out["ent_cnt_1h"].astype("float64") / daily
            out["burst_ratio_1h"] = ratio.where(daily > 0)
    return out


def build_batch_inputs(
    features: pd.DataFrame,
    merged: pd.DataFrame,
    feature_cols: list[str],
    raw_cols: list[str],
    key_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Rule input indexed by TransactionID: features + raw fields + past-only email_ent_known.

    merged must contain raw_cols, key_cols (cooldown time + entity columns) and the Step 6 email
    source columns (RAW_SOURCE_COLUMNS).
    """
    merged = merged.loc[features.index]
    out = features[feature_cols].copy()
    for col in [*raw_cols, *(key_cols or [])]:
        out[col] = merged[col]
    out[EMAIL_KNOWN] = email_known_batch(merged[RAW_SOURCE_COLUMNS])
    return out


def merged_columns(raw_cols: list[str], key_cols: list[str] | None = None) -> list[str]:
    """Columns to read from merged.parquet for build_batch_inputs."""
    return list(dict.fromkeys([*RAW_SOURCE_COLUMNS, *raw_cols, *(key_cols or [])]))
