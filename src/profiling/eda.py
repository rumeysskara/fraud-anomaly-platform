"""EDA helpers (label-free). Group builders for the fraud-rate tables never see the label."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.profiling.config import profiling_config

MISSING = "(eksik)"
OTHER = "(diğer)"


def eda_config() -> dict:
    """The `eda` section of configs/profiling.yaml."""
    return profiling_config("eda")


def top_n() -> int:
    """Number of top categories to show (shared with distributions.top_n)."""
    return int(profiling_config("distributions")["top_n"])


def value_share(s: pd.Series, n: int | None = None) -> pd.DataFrame:
    """Count and share per value (NaN shown as (eksik)); top-n by count if n is given."""
    label = s.astype(object).where(s.notna(), MISSING).astype(str)
    vc = label.value_counts()
    if n is not None:
        vc = vc.head(n)
    return pd.DataFrame({"value": vc.index, "n": vc.to_numpy(), "share": vc.to_numpy() / len(s)})


def daily_counts(dt: pd.Series) -> pd.Series:
    """Transactions per calendar day, zero-filled between first and last day."""
    days = dt.dt.normalize().value_counts().sort_index()
    full = pd.date_range(days.index.min(), days.index.max(), freq="D")
    return days.reindex(full, fill_value=0).rename("n")


def autocorrelation(counts: pd.Series, cfg: dict | None = None) -> pd.DataFrame:
    """Autocorrelation of the daily series for each lag, raw and with a 7-day mean removed.

    The detrended series subtracts a centred 7-day rolling mean, which removes the level/trend
    but keeps a weekly pattern.
    """
    cfg = cfg or eda_config()
    lags = range(cfg["acf_min_lag"], cfg["acf_max_lag"] + 1)
    resid = counts - counts.rolling(cfg["week_days"], center=True).mean()
    rows = [
        {"lag": lag, "acf_raw": counts.autocorr(lag), "acf_detrended": resid.autocorr(lag)}
        for lag in lags
    ]
    return pd.DataFrame(rows)


def weekday_profile(counts: pd.Series) -> pd.DataFrame:
    """Mean daily count per day of week (0 = Monday) relative to the overall mean."""
    by = counts.groupby(counts.index.dayofweek).mean()
    return pd.DataFrame(
        {
            "dayofweek": by.index,
            "mean_daily_n": by.to_numpy(),
            "ratio_to_mean": by.to_numpy() / counts.mean(),
        }
    )


def window_stats(
    counts: pd.Series, start: int, end: int, ref_date: pd.Timestamp, cfg: dict | None = None
) -> dict:
    """Mean daily count inside day offsets [start, end] vs the week_days before and after."""
    week = (cfg or eda_config())["week_days"]
    day = (counts.index - ref_date).days
    inside = counts[(day >= start) & (day <= end)]
    before = counts[(day >= start - week) & (day < start)]
    after = counts[(day > end) & (day <= end + week)]
    return {
        "start_day": start,
        "end_day": end,
        "start_date": str((ref_date + pd.Timedelta(days=start)).date()),
        "end_date": str((ref_date + pd.Timedelta(days=end)).date()),
        "mean_inside": float(inside.mean()),
        "mean_before_7d": float(before.mean()),
        "mean_after_7d": float(after.mean()),
        "ratio_inside_vs_surround": float(inside.mean() / pd.concat([before, after]).mean()),
    }


def best_peak_window(
    counts: pd.Series, ref_date: pd.Timestamp, cfg: dict | None = None
) -> tuple[int, int]:
    """Day offsets of the peak_len-day window with the highest mean count (day <= search max)."""
    cfg = cfg or eda_config()
    peak_len = cfg["peak_len"]
    day = (counts.index - ref_date).days
    sub = counts[day <= cfg["peak_search_max_day"]]
    roll = sub.rolling(peak_len).mean()
    end = roll.idxmax()
    return int((end - ref_date).days - peak_len + 1), int((end - ref_date).days)


def spike_stats(counts: pd.Series, ref_date: pd.Timestamp, cfg: dict | None = None) -> dict:
    """Size of the jump on the config spike_day: vs previous day, prior week mean, level shift."""
    cfg = cfg or eda_config()
    spike_day, week = cfg["spike_day"], cfg["week_days"]
    day = (counts.index - ref_date).days
    at = float(counts[day == spike_day].iloc[0])
    prev = float(counts[day == spike_day - 1].iloc[0])
    before = counts[(day >= spike_day - week) & (day < spike_day)]
    after = counts[(day > spike_day) & (day <= spike_day + week)]
    return {
        "spike_day": spike_day,
        "date": str((ref_date + pd.Timedelta(days=spike_day)).date()),
        "count": at,
        "previous_day": prev,
        "ratio_vs_previous_day": at / prev,
        "mean_prior_7d": float(before.mean()),
        "ratio_vs_prior_7d_mean": at / float(before.mean()),
        "mean_next_7d": float(after.mean()),
        "level_shift_next7_vs_prior7": float(after.mean() / before.mean()),
        "next_day_count": float(counts[day == spike_day + 1].iloc[0]),
    }


def top_amounts(amount: pd.Series, cfg: dict | None = None) -> pd.DataFrame:
    """Most frequent TransactionAmt values with count and share of all rows."""
    cfg = cfg or eda_config()
    vc = (
        amount.astype("float64")
        .round(cfg["amount_decimals"])
        .value_counts()
        .head(cfg["top_amounts"])
    )
    return pd.DataFrame(
        {
            "amount": vc.index.astype("float64"),
            "n": vc.to_numpy(),
            "share": vc.to_numpy() / len(amount),
        }
    )


# --- label-free group builders for the fit-only fraud-rate tables ------------------------


def category_groups(s: pd.Series, n: int | None = None) -> pd.Series:
    """Group labels: top-n values by frequency, the rest (diger), NaN as (eksik).

    Result is categorical ordered by frequency (top first), so tables keep that order.
    """
    label = s.astype(object).where(s.notna(), MISSING).astype(str)
    order = list(label.value_counts().index)
    if n is not None and len(order) > n:
        keep = [v for v in order if v != MISSING][:n]
        label = label.where(label.isin(keep) | (label == MISSING), OTHER)
        order = keep + [OTHER] + ([MISSING] if (label == MISSING).any() else [])
    return pd.Series(pd.Categorical(label, categories=order, ordered=True), index=s.index)


def hour_groups(dt: pd.Series) -> pd.Series:
    """Hour of day (0-23) of the reference-dated datetime."""
    return pd.Series(dt.dt.hour.to_numpy(), index=dt.index, name="hour")


def decile_groups(amount: pd.Series, cfg: dict | None = None) -> pd.Series:
    """TransactionAmt decile labels D1..D10 with bounds learned from this (fit) series."""
    count = (cfg or eda_config())["decile_count"]
    edges = np.unique(amount.quantile(np.linspace(0, 1, count + 1)).to_numpy())
    codes = pd.cut(amount, bins=edges, include_lowest=True)
    labels = [
        f"D{i + 1} ({iv.left:.0f}-{iv.right:.0f})" for i, iv in enumerate(codes.cat.categories)
    ]
    return pd.Series(
        pd.Categorical.from_codes(codes.cat.codes, labels, ordered=True), index=amount.index
    )


def d1_zero_groups(d1: pd.Series) -> pd.Series:
    """D1 == 0 (new card) vs other vs missing."""
    out = np.where(d1.isna(), MISSING, np.where(d1 == 0, "D1=0 (yeni kart)", "D1>0"))
    return pd.Series(
        pd.Categorical(out, ["D1=0 (yeni kart)", "D1>0", MISSING], ordered=True), index=d1.index
    )


def dominant_value_groups(s: pd.Series) -> tuple[pd.Series, object]:
    """Most frequent value (learned from this fit series) vs other vs missing."""
    mode = s.mode(dropna=True).iloc[0]
    dom = f"baskın ({mode:g})" if isinstance(mode, int | float | np.number) else f"baskın ({mode})"
    out = np.where(s.isna(), MISSING, np.where(s == mode, dom, "diğer"))
    cats = [dom, "diğer", MISSING]
    return pd.Series(pd.Categorical(out, cats, ordered=True), index=s.index), mode


def email_match_groups(p: pd.Series, r: pd.Series) -> pd.Series:
    """P vs R email domain: equal / different (both present); P only; P missing."""
    both = p.notna() & r.notna()
    same = p.astype(object) == r.astype(object)
    out = np.select(
        [both & same, both & ~same, p.notna() & r.isna()],
        ["P = R (ikisi dolu)", "P != R (ikisi dolu)", "yalnız P dolu (R eksik)"],
        default="P eksik",
    )
    cats = ["P = R (ikisi dolu)", "P != R (ikisi dolu)", "yalnız P dolu (R eksik)", "P eksik"]
    return pd.Series(pd.Categorical(out, cats, ordered=True), index=p.index)
