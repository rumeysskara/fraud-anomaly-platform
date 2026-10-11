"""Data loading: transaction + identity LEFT JOIN, SAMPLE_N, time split.

This module is one of only two places where isFraud is read (the other is
src/evaluation). The label is returned as a separate Series `y` and never
stays in the feature DataFrame. There is a single loading path: load_merged
(memory-friendly, chunked); load_data is a thin wrapper that drops the join stats.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.config import RAW_DIR, get_sample_n, load_settings, load_yaml


def downcast(df: pd.DataFrame) -> pd.DataFrame:
    """Downcast numeric columns to save memory (floats to float32, ints to smallest)."""
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].astype("float32")
    for col in df.select_dtypes(include=["int64", "int32"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    return df


def add_datetime(
    df: pd.DataFrame, reference_date: str | None = None, time_col: str | None = None
) -> pd.Series:
    """Return reference_date + TransactionDT seconds (documented assumption).

    Both arguments default to settings.yaml (time.reference_date, time.time_column).
    """
    time_cfg = load_settings()["time"]
    reference_date = reference_date or time_cfg["reference_date"]
    time_col = time_col or time_cfg["time_column"]
    return pd.Timestamp(reference_date) + pd.to_timedelta(df[time_col].astype("int64"), unit="s")


HAS_IDENTITY_COL = "has_identity"


def _read_downcast(path: Path, nrows: int | None = None) -> pd.DataFrame:
    """Read a CSV in chunks, downcasting every chunk before concatenation."""
    chunksize = load_yaml("profiling.yaml")["loading"]["chunksize"]
    parts = []
    for chunk in pd.read_csv(path, nrows=nrows, chunksize=chunksize):
        parts.append(downcast(chunk))
    df = pd.concat(parts, ignore_index=True)
    del parts
    return df


def _strings_to_category(df: pd.DataFrame) -> pd.DataFrame:
    """Convert string columns to category when n_unique / n_rows is below the config ratio."""
    max_ratio = load_yaml("profiling.yaml")["loading"]["category_max_ratio"]
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) or isinstance(df[col].dtype, pd.CategoricalDtype):
            continue
        if df[col].nunique(dropna=True) <= max_ratio * max(len(df), 1):
            df[col] = df[col].astype("category")
    return df


def load_merged(
    data_dir: Path | None = None,
    sample_n: int | None = None,
    settings: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series, dict[str, int]]:
    """Memory-friendly LEFT JOIN of transaction and identity.

    Returns (X, y, stats). X is indexed by TransactionID, sorted by TransactionDT, has a
    boolean `has_identity` column and no label. y is the label as a separate Series.
    stats holds join counts (transaction rows, identity rows, matched rows, duplicates).
    """
    settings = settings or load_settings()
    cfg = settings["data"]
    id_col, label_col = cfg["id_column"], cfg["label_column"]
    time_col = settings["time"]["time_column"]
    data_dir = Path(data_dir) if data_dir else RAW_DIR
    sample_n = sample_n if sample_n is not None else get_sample_n()

    trans = _read_downcast(data_dir / cfg["transaction_file"], nrows=sample_n or None)
    if not trans[time_col].is_monotonic_increasing:
        trans = trans.sort_values([time_col, id_col], kind="stable", ignore_index=True)
    ident_all = _read_downcast(data_dir / cfg["identity_file"])
    ident = ident_all[ident_all[id_col].isin(trans[id_col])]
    stats = {
        "transaction_rows": len(trans),
        "identity_rows_in_file": len(ident_all),
        "identity_rows_in_scope": len(ident),
        "duplicate_transaction_ids": int(trans[id_col].duplicated().sum()),
        "duplicate_identity_ids": int(ident[id_col].duplicated().sum()),
    }
    del ident_all

    ident[HAS_IDENTITY_COL] = True  # small frame; avoids inserting a column into the big one
    df = trans.merge(ident, on=id_col, how="left", validate="one_to_one")
    df[HAS_IDENTITY_COL] = df[HAS_IDENTITY_COL].eq(True)
    del trans, ident
    stats["rows_after_join"] = len(df)
    stats["matched_rows"] = int(df[HAS_IDENTITY_COL].sum())
    df = df.set_index(id_col)

    y = df.pop(label_col).astype("int8")
    return _strings_to_category(df), y, stats


def load_data(
    data_dir: Path | None = None,
    sample_n: int | None = None,
    settings: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Load and join the data; return (X, y) sorted by TransactionDT.

    X is indexed by TransactionID, has a boolean `has_identity` column and no label.
    sample_n (or the SAMPLE_N env var when None) reads only the first N rows of the
    transaction file; identity is filtered to those TransactionIDs.
    """
    X, y, _ = load_merged(data_dir, sample_n, settings)
    return X, y


def split_by_time(
    df: pd.DataFrame, ratio: float | None = None, time_col: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by time order: first `ratio` rows = fit, rest = holdout. No shuffling.

    ratio and time_col default to settings.yaml (split.fit_ratio, time.time_column).
    Align y with `y.loc[fit.index]` / `y.loc[holdout.index]`.
    """
    settings = load_settings()
    ratio = settings["split"]["fit_ratio"] if ratio is None else ratio
    time_col = time_col or settings["time"]["time_column"]
    ordered = df.sort_values(time_col, kind="stable")
    cut = int(len(ordered) * ratio)
    return ordered.iloc[:cut], ordered.iloc[cut:]
