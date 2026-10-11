"""Outliers, distributions and rare categories."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.profiling.config import profiling_config


def outlier_row(name: str, values: pd.Series, cfg: dict | None = None) -> dict:
    """IQR fences and robust z-score (median/MAD) outlier counts for one numeric column."""
    cfg = cfg or profiling_config("outliers")
    z_cut, iqr_k, scale = cfg["robust_z_cut"], cfg["iqr_k"], cfg["robust_z_scale"]
    x = values.dropna().to_numpy(dtype="float64")
    row: dict = {"column": name, "n": int(x.size)}
    if x.size == 0:
        return row
    q1, med, q3 = np.percentile(x, [25, 50, 75])
    iqr = q3 - q1
    lo, hi = q1 - iqr_k * iqr, q3 + iqr_k * iqr
    mad = float(np.median(np.abs(x - med)))
    n_iqr = int(((x < lo) | (x > hi)).sum())
    row.update(
        median=med,
        q1=q1,
        q3=q3,
        iqr=iqr,
        lower_fence=lo,
        upper_fence=hi,
        n_iqr_outliers=n_iqr,
        iqr_outlier_ratio=n_iqr / x.size,
        mad=mad,
        mad_is_zero=mad == 0,
    )
    if mad > 0:
        n_z = int((np.abs(scale * (x - med) / mad) > z_cut).sum())
        row.update(n_robust_z_outliers=n_z, robust_z_outlier_ratio=n_z / x.size)
    return row


def outlier_table(df: pd.DataFrame, cols: list[str], cfg: dict | None = None) -> pd.DataFrame:
    """Outlier table for numeric columns; config log_columns are also analysed on log1p."""
    cfg = cfg or profiling_config("outliers")
    rows = [outlier_row(c, df[c], cfg) for c in cols]
    for c in cfg["log_columns"]:
        if c in df.columns:
            rows.append(outlier_row(f"{c}__log1p", np.log1p(df[c].astype("float64")), cfg))
    return pd.DataFrame(rows)


def numeric_distributions(
    df: pd.DataFrame, cols: list[str], cfg: dict | None = None
) -> pd.DataFrame:
    """Count, mean, std, min/max, skewness, kurtosis and quantiles per numeric column."""
    quantiles = (cfg or profiling_config("distributions"))["quantiles"]
    rows = []
    for c in cols:
        s = df[c].astype("float64")
        row = {
            "column": c,
            "count": int(s.notna().sum()),
            "mean": s.mean(),
            "std": s.std(),
            "min": s.min(),
            "max": s.max(),
            "skew": s.skew(),
            "kurtosis": s.kurt(),
        }
        for q, v in zip(quantiles, s.quantile(quantiles), strict=True):
            row[f"q{int(q * 100):02d}"] = v
        rows.append(row)
    return pd.DataFrame(rows)


def categorical_topn(df: pd.DataFrame, cols: list[str], n: int | None = None) -> pd.DataFrame:
    """Top-n value frequencies per categorical column (ratio over all rows, NaN included)."""
    n = n or profiling_config("distributions")["top_n"]
    parts = []
    total = max(len(df), 1)
    for c in cols:
        vc = df[c].value_counts(dropna=False).head(n)
        part = pd.DataFrame(
            {
                "column": c,
                "rank": np.arange(1, len(vc) + 1),
                "value": vc.index.astype(str),
                "count": vc.to_numpy(),
                "ratio": vc.to_numpy() / total,
            }
        )
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def rare_combinations(
    df: pd.DataFrame,
    key_sets: list[list[str]],
    cfg: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Find rare value combinations (NaN counts as its own value).

    A combination is rare when its row share is below rare_ratio. Returns
    (detail, summary): detail lists the rarest combos (capped), summary has totals per set.
    """
    cfg = cfg or profiling_config("rare")
    rare_ratio, max_rows_per_set = cfg["rare_ratio"], cfg["max_rows_per_set"]
    total = max(len(df), 1)
    details, summaries = [], []
    for cols in key_sets:
        counts = df.groupby(cols, observed=True, dropna=False).size()
        counts = counts[counts > 0].reset_index(name="count")
        counts["ratio"] = counts["count"] / total
        counts["is_rare"] = counts["ratio"] < rare_ratio
        name = "|".join(cols)
        rare = counts[counts["is_rare"]]
        summaries.append(
            {
                "key_set": name,
                "n_combinations": len(counts),
                "n_rare": len(rare),
                "rare_combination_share": len(rare) / max(len(counts), 1),
                "rows_in_rare": int(rare["count"].sum()),
                "rows_in_rare_ratio": rare["count"].sum() / total,
            }
        )
        values = pd.Series(" | ".join(map(str, r)) for r in rare[cols].itertuples(index=False))
        values.index = rare.index
        det = pd.DataFrame(
            {"key_set": name, "values": values, "count": rare["count"], "ratio": rare["ratio"]}
        )
        details.append(det.sort_values(["count", "values"]).head(max_rows_per_set))
    detail = pd.concat(details, ignore_index=True) if details else pd.DataFrame()
    return detail, pd.DataFrame(summaries)
