"""Derived columns used by context conditions. Same code for batch and single records."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

LAYER_SCORE_SUFFIX = "_score"
EMAIL_KNOWN = "email_ent_known"

# Columns the engine needs in every input (features.parquet + merged.parquet + Step 4 layers).
FEATURE_COLUMNS = [
    "local_hour_est",
    "is_weekend",
    "is_low_volume_window",
    "ent_txn_count",
    "ent_age_days",
    "ent_cnt_24h",
    "amt_zscore_ent",
    "device_ent_match",
    "amt_has_3dec",
    "holiday_season",
    "card_age_days",
    "small_amt_streak_1h",
]
RAW_COLUMNS = ["TransactionAmt", "ProductCD", "addr2"]
DERIVED_COLUMNS = [
    "abs_amt_zscore_ent",
    "known_device_or_email",
    "ent_daily_avg",
    "burst_ratio_24h",
    "dominant_layer",
]


def layer_columns(weights: dict[str, float]) -> list[str]:
    """Names of the Step 4 layer score columns, e.g. temporal_score."""
    return [f"{name}{LAYER_SCORE_SUFFIX}" for name in weights]


def required_columns(weights: dict[str, float]) -> list[str]:
    """All input columns the engine reads (before derivation)."""
    return [*FEATURE_COLUMNS, *RAW_COLUMNS, EMAIL_KNOWN, *layer_columns(weights)]


def dominant_layer(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Layer with the largest weighted contribution w_i * s_i (first one on ties)."""
    names = list(weights)
    contrib = np.column_stack(
        [weights[n] * df[f"{n}{LAYER_SCORE_SUFFIX}"].to_numpy("float64") for n in names]
    )
    contrib = np.nan_to_num(contrib, nan=-1.0)
    return pd.Series(np.asarray(names, dtype=object)[contrib.argmax(axis=1)], index=df.index)


def add_derived(
    df: pd.DataFrame, weights: dict[str, float], derived: dict[str, Any]
) -> pd.DataFrame:
    """Return a copy of df with the derived columns added.

    - abs_amt_zscore_ent = |amt_zscore_ent|
    - known_device_or_email = this device was used by the entity before (device_ent_match >= 1)
      or this e-mail domain was used by the entity before (email_ent_known == 1); past only
    - ent_daily_avg = ent_txn_count / max(ent_age_days, daily_avg_min_days)
    - burst_ratio_24h = ent_cnt_24h / ent_daily_avg (NaN without history)
    - dominant_layer = layer with the largest weighted contribution (Step 5 weights)
    """
    out = df.copy()
    min_days = float(derived.get("daily_avg_min_days", 1.0))
    count = out["ent_txn_count"].astype("float64")
    out["abs_amt_zscore_ent"] = out["amt_zscore_ent"].astype("float64").abs()
    device_known = out["device_ent_match"].astype("float64") >= 1
    email_known = out[EMAIL_KNOWN].astype("float64") >= 1
    out["known_device_or_email"] = (device_known | email_known).astype("int8")
    age = out["ent_age_days"].astype("float64").clip(lower=min_days)
    daily = count / age
    out["ent_daily_avg"] = daily
    out["burst_ratio_24h"] = (out["ent_cnt_24h"].astype("float64") / daily).where(daily > 0)
    out["dominant_layer"] = dominant_layer(out, weights)
    return out
