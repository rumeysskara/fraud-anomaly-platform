"""Missing-data and data-quality tables."""

from __future__ import annotations

import pandas as pd

from src.profiling.config import profiling_config


def missing_table(df: pd.DataFrame, schema: pd.DataFrame) -> pd.DataFrame:
    """Per-column null count/ratio plus a null_block id.

    Columns of the same group with an identical null count share a block; V columns
    typically come in such blocks (they are missing together).
    """
    cols = schema[schema["column"].isin(df.columns)].copy()
    cols["null_count"] = [int(df[c].isna().sum()) for c in cols["column"]]
    cols["null_ratio"] = cols["null_count"] / max(len(df), 1)
    cols["null_block"] = cols["group"] + ":" + cols["null_count"].astype(str)
    return cols[["column", "group", "null_count", "null_ratio", "null_block"]].reset_index(
        drop=True
    )


def group_missing(missing: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    """Group-level summary: size, mean/min/max null ratio, #cols above high_null, #blocks."""
    high_null = (cfg or profiling_config("quality"))["high_null"]
    g = missing.groupby("group")
    out = pd.DataFrame(
        {
            "n_columns": g.size(),
            "mean_null_ratio": g["null_ratio"].mean(),
            "min_null_ratio": g["null_ratio"].min(),
            "max_null_ratio": g["null_ratio"].max(),
            "n_cols_over_threshold": g["null_ratio"].apply(lambda s: int((s > high_null).sum())),
            "n_null_blocks": g["null_block"].nunique(),
        }
    )
    return out.reset_index().sort_values("n_columns", ascending=False, ignore_index=True)


def quality_checks(df: pd.DataFrame, schema: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    """Long table of findings: constant cols, >high_null cols, duplicates, range violations."""
    cfg = cfg or profiling_config("quality")
    high_null, amount = cfg["high_null"], cfg["amount_column"]
    rows: list[dict] = []
    for _, r in schema.iterrows():
        if r["cardinality_class"] == "constant":
            rows.append({"check": "constant_column", "column": r["column"], "value": r["n_unique"]})
        if r["null_ratio"] > high_null:
            rows.append(
                {"check": "high_null_column", "column": r["column"], "value": r["null_ratio"]}
            )
    rows.append({"check": "duplicate_rows", "column": "*", "value": float(df.duplicated().sum())})
    rows.append(
        {"check": "duplicate_index", "column": "*", "value": float(df.index.duplicated().sum())}
    )
    groups = schema.set_index("column")["group"]
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            continue
        if groups.get(col) in cfg["non_negative_groups"] or col in cfg["non_negative_columns"]:
            n_neg = int((df[col] < 0).sum())
            if n_neg:
                rows.append({"check": "negative_value", "column": col, "value": float(n_neg)})
    if amount in df.columns:
        rows.append(
            {
                "check": "non_positive_amount",
                "column": amount,
                "value": float((df[amount] <= 0).sum()),
            }
        )
    return pd.DataFrame(rows, columns=["check", "column", "value"])
