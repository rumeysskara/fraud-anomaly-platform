"""Rule-based column schema: group, inferred type, null ratio, cardinality class."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from src.profiling.config import profiling_config

GROUP_RE = re.compile(r"^(.*?)_?(\d+)$")

# The only name-based override is `coded_categorical_groups` in configs/profiling.yaml
# (IEEE-CIS data dictionary); every other type comes from data-driven rules.


def column_group(name: str) -> str:
    """Group by the prefix before the trailing number (V12 -> V, id_05 -> id, else other)."""
    match = GROUP_RE.match(name)
    return match.group(1) if match and match.group(1) else "other"


def cardinality_class(n_unique: int, cfg: dict | None = None) -> str:
    """constant (<=1) | low | medium | high, thresholds from the `schema` config section."""
    cfg = cfg or profiling_config("schema")
    if n_unique <= 1:
        return "constant"
    if n_unique <= cfg["low_card_max"]:
        return "low"
    if n_unique <= cfg["high_card_abs"]:
        return "medium"
    return "high"


def _is_integral(values: pd.Series) -> bool:
    """True when all non-null values of a numeric series are whole numbers."""
    arr = values.dropna().to_numpy(dtype="float64")
    return bool(arr.size) and bool(np.all(arr == np.floor(arr)))


def infer_type(
    series: pd.Series,
    group: str,
    n_unique: int,
    time_col: str | None = None,
    cfg: dict | None = None,
) -> tuple[str, str]:
    """Return (inferred_type, type_source) for a column.

    Types: numeric | categorical | datetime | id | flag. type_source is 'rule' or
    'dictionary' (the coded-categorical groups override).
    """
    cfg = cfg or profiling_config("schema")
    id_unique_ratio, id_min_unique = cfg["id_unique_ratio"], cfg["id_min_unique"]
    if time_col is not None and series.name == time_col:
        return "datetime", "config"
    non_null = int(series.notna().sum())
    ratio = n_unique / non_null if non_null else 0.0
    if pd.api.types.is_bool_dtype(series) or n_unique <= 2:
        return "flag", "rule"
    is_num = pd.api.types.is_numeric_dtype(series)
    if is_num and group in cfg["coded_categorical_groups"]:
        return "categorical", "dictionary"
    if not is_num:
        if ratio > id_unique_ratio and n_unique > id_min_unique:
            return "id", "rule"
        return "categorical", "rule"
    integral = _is_integral(series)
    if integral and ratio > id_unique_ratio and n_unique > id_min_unique:
        return "id", "rule"
    if integral and n_unique <= cfg["int_categorical_max"]:
        return "categorical", "rule"
    return "numeric", "rule"


def infer_schema(
    df: pd.DataFrame,
    time_col: str | None = None,
    cfg: dict | None = None,
) -> pd.DataFrame:
    """Build the column schema. The index (TransactionID) is included as an 'id' row."""
    cfg = cfg or profiling_config("schema")
    rows = []
    n_rows = len(df)
    items = [(df.index.name or "index", df.index.to_series())] if df.index.name else []
    items += [(c, df[c]) for c in df.columns]
    for name, s in items:
        n_unique = int(s.nunique(dropna=True))
        group = column_group(name)
        if name == df.index.name:
            kind, source = "id", "rule"
        else:
            kind, source = infer_type(s, group, n_unique, time_col, cfg)
        card = cardinality_class(n_unique, cfg)
        rows.append(
            {
                "column": name,
                "group": group,
                "dtype": str(s.dtype),
                "inferred_type": kind,
                "type_source": source,
                "null_ratio": float(s.isna().mean()) if n_rows else 0.0,
                "n_unique": n_unique,
                "unique_ratio": n_unique / n_rows if n_rows else 0.0,
                "cardinality_class": card,
                "is_high_cardinality": bool(card == "high" and kind in ("categorical", "id")),
            }
        )
    return pd.DataFrame(rows)
