"""Statistics learned on the FIT set only (leakage rule: fit/transform separation)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.features.timecal import (
    CalendarSpec,
    detect_season,
    epoch_day_to_date,
    hourly_counts,
    lowest_window_start,
)
from src.features.utils import amount_array, get_col, value_keys

GROUP_COLUMNS = {"card4_card6": ["card4", "card6"], "addr1": ["addr1"]}


def group_keys(df: pd.DataFrame, name: str) -> pd.Series:
    """Group key of a log-amount deviation group (card4+card6, or addr1)."""
    key = value_keys(get_col(df, GROUP_COLUMNS[name][0]))
    for col in GROUP_COLUMNS[name][1:]:
        key = key + "|" + value_keys(get_col(df, col))
    return key


@dataclass
class LearnedStats:
    """Everything the transform needs from the fit set."""

    n_fit: int
    low_volume_start_hour: int
    local_offset_hours: int
    hourly_counts: list[int]
    small_amt_threshold: float
    dominant_addr2: float
    amt_mean: float
    amt_std: float
    amt_cent_share: pd.Series  # index = amount in cents, value = share of fit rows
    common_cents: list[int]
    product_amounts: dict[str, np.ndarray]
    all_amounts: np.ndarray
    log_mean: float
    log_std: float
    group_stats: dict[str, pd.DataFrame]  # name -> DataFrame(mean, std) indexed by key
    freq_tables: dict[str, pd.Series]  # column -> share by value key (NaN included)
    combo_share: pd.Series  # (id_30|id_31) key -> share
    season: dict | None = None  # learned holiday_season window (epoch days), see detect_season
    passthrough_cols: list[str] = field(default_factory=list)

    @property
    def season_days(self) -> tuple[int, int] | None:
        """(start, end) epoch days of the season window, or None."""
        return (self.season["start_day"], self.season["end_day"]) if self.season else None

    def as_config_block(self) -> dict:
        """Scalar values worth showing in configs/entity.yaml (`learned:`)."""
        season = {}
        if self.season:
            season = {
                "season_start_date": epoch_day_to_date(self.season["start_day"]),
                "season_end_date": epoch_day_to_date(self.season["end_day"]),
                "season_mean_ratio": round(self.season["mean_ratio"], 3),
            }
        return {
            "low_volume_start_hour": self.low_volume_start_hour,
            "local_offset_hours": self.local_offset_hours,
            "small_amt_threshold": round(self.small_amt_threshold, 4),
            "dominant_addr2": self.dominant_addr2,
            **season,
            "n_fit": self.n_fit,
        }


def passthrough_columns(columns: list[str], cfg: dict, clusters: pd.DataFrame | None) -> list[str]:
    """Raw V/C/D columns kept: cluster representatives plus columns outside any cluster."""
    groups = tuple(cfg["groups"])
    pat = re.compile(r"^(" + "|".join(groups) + r")\d+$")
    drop: set[str] = set()
    if clusters is not None and len(clusters):
        drop = set(clusters.loc[clusters["column"] != clusters["representative"], "column"])
    excl = set(cfg.get("exclude", []))
    return [c for c in columns if pat.match(c) and c not in drop and c not in excl]


def fit_stats(
    df: pd.DataFrame,
    cfg: dict,
    cal: CalendarSpec,
    clusters: pd.DataFrame | None = None,
) -> LearnedStats:
    """Learn all fit statistics from the fit frame `df` (no label involved)."""
    dt = df["TransactionDT"].to_numpy("int64")
    amt = amount_array(df)
    counts = hourly_counts(dt, cal.ref_seconds)
    start = lowest_window_start(counts, cal.low_volume_length)
    override = cfg["local_time"].get("offset_override_hours")
    offset = int(override) if override is not None else -start

    addr2 = get_col(df, "addr2").dropna()
    dominant = float(addr2.mode().iloc[0]) if len(addr2) else float("nan")

    cents = np.rint(amt * 100).astype("int64")
    share = pd.Series(cents).value_counts(normalize=True)
    common = [int(c) for c in share.index[: cfg["amount"]["common_top_n"]]]

    prod = value_keys(get_col(df, "ProductCD")).to_numpy()
    product_amounts = {p: np.sort(amt[prod == p]) for p in np.unique(prod)}

    loga = np.log1p(amt)
    min_rows = cfg["amount"]["group_min_rows"]
    group_stats = {}
    for name in GROUP_COLUMNS:
        g = pd.Series(loga).groupby(group_keys(df, name).to_numpy()).agg(["mean", "std", "count"])
        group_stats[name] = g[g["count"] >= min_rows][["mean", "std"]]

    freq = {}
    for col in cfg["freq_columns"]:
        freq[col] = value_keys(get_col(df, col)).value_counts(normalize=True)
    c1, c2 = cfg["rare_combo"]["columns"]
    combo = value_keys(get_col(df, c1)) + "|" + value_keys(get_col(df, c2))

    return LearnedStats(
        n_fit=len(df),
        low_volume_start_hour=start,
        local_offset_hours=offset,
        hourly_counts=[int(c) for c in counts],
        small_amt_threshold=float(np.quantile(amt, cfg["small_amount"]["quantile"])),
        dominant_addr2=dominant,
        amt_mean=float(amt.mean()),
        amt_std=float(amt.std(ddof=1)),
        amt_cent_share=share,
        common_cents=common,
        product_amounts=product_amounts,
        all_amounts=np.sort(amt),
        log_mean=float(loga.mean()),
        log_std=float(loga.std(ddof=1)),
        group_stats=group_stats,
        freq_tables=freq,
        combo_share=combo.value_counts(normalize=True),
        season=detect_season(dt, cal.ref_seconds, cfg["holidays"]["season"])[0],
        passthrough_cols=passthrough_columns(list(df.columns), cfg["passthrough"], clusters),
    )
