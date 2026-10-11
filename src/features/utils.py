"""Small helpers shared by batch and online feature code."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

NA_KEY = "__NA__"


def value_keys(s: pd.Series) -> pd.Series:
    """Return a string key per value; NaN becomes NA_KEY.

    Numbers are keyed through float64 so that 87, 87.0 and float32(87) give the same key
    (batch frames and online dicts therefore agree).
    """
    if pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype):
        f = s.astype("float64")
        return f.astype(str).where(f.notna(), NA_KEY)
    return s.astype(object).where(s.notna(), NA_KEY).astype(str)


def get_col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return df[name], or an all-NaN column when the input does not have it."""
    if name in df.columns:
        return df[name]
    return pd.Series(np.nan, index=df.index, dtype="float64")


def amount_array(df: pd.DataFrame, column: str = "TransactionAmt") -> np.ndarray:
    """Amounts as float64 after a float32 round trip (the dtype stored in merged.parquet)."""
    return df[column].astype("float32").astype("float64").to_numpy()


def entity_keys(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Entity key = joined value keys of the entity columns (NaN is its own level)."""
    key = value_keys(get_col(df, columns[0]))
    for col in columns[1:]:
        key = key + "|" + value_keys(get_col(df, col))
    return key


def to_python(value: Any) -> Any:
    """Convert numpy scalars to plain Python values (for JSON-friendly dicts)."""
    return value.item() if isinstance(value, np.generic) else value
