"""Data loading: transaction + identity LEFT JOIN, SAMPLE_N, time split.

This module is one of only two places where isFraud is read (the other is
src/evaluation). The label is returned as a separate Series `y` and never
stays in the feature DataFrame.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.config import RAW_DIR, get_sample_n, load_settings


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


def load_data(
    data_dir: Path | None = None,
    sample_n: int | None = None,
    settings: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Load and join the data; return (X, y) sorted by TransactionDT.

    X is indexed by TransactionID and has no label column. sample_n (or the SAMPLE_N
    env var when None) reads only the first N rows of the transaction file (sorted by
    TransactionDT on disk); identity is filtered to those TransactionIDs.
    """
    settings = settings or load_settings()
    cfg = settings["data"]
    id_col, label_col = cfg["id_column"], cfg["label_column"]
    time_col = settings["time"]["time_column"]
    data_dir = Path(data_dir) if data_dir else RAW_DIR
    sample_n = sample_n if sample_n is not None else get_sample_n()

    # The file is ordered by TransactionDT, so nrows reads the earliest N rows only.
    trans = pd.read_csv(data_dir / cfg["transaction_file"], nrows=sample_n or None)
    trans = trans.sort_values([time_col, id_col], kind="stable")
    ids = set(trans[id_col])
    chunks = pd.read_csv(data_dir / cfg["identity_file"], chunksize=100_000)
    ident = pd.concat([c[c[id_col].isin(ids)] for c in chunks], ignore_index=True)
    df = trans.merge(ident, on=id_col, how="left").set_index(id_col)
    del trans, ident

    y = df.pop(label_col).astype("int8")
    return downcast(df), y


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
