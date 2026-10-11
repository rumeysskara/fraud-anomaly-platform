"""Row-wise features: need only the current transaction plus fit statistics (no history)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.learned import LearnedStats, group_keys
from src.features.timecal import CalendarSpec, calendar_features
from src.features.utils import amount_array, get_col, value_keys

ID_COLUMNS_HINT = "id_"


def _n_decimals(amt: np.ndarray) -> np.ndarray:
    """Number of decimals (0-3) of the amount; 3 decimals = possible currency conversion."""
    milli = np.rint(amt * 1000).astype("int64")
    return np.where(
        milli % 10 != 0, 3, np.where(milli % 100 != 0, 2, np.where(milli % 1000 != 0, 1, 0))
    )


def _product_quantile(amt: np.ndarray, product: np.ndarray, L: LearnedStats) -> np.ndarray:
    """Amount percentile within the transaction's ProductCD (fit distribution)."""
    out = np.empty(len(amt))
    for p in np.unique(product):
        mask = product == p
        ref = L.product_amounts.get(p, L.all_amounts)
        out[mask] = np.searchsorted(ref, amt[mask], side="right") / len(ref)
    return out


def _group_deviation(
    loga: np.ndarray, keys: pd.Series, stats: pd.DataFrame, L: LearnedStats, floor: float
) -> np.ndarray:
    """(log amount - group mean) / group std; unseen or small groups use the global fit values."""
    mean = keys.map(stats["mean"]).fillna(L.log_mean).to_numpy()
    std = keys.map(stats["std"]).fillna(L.log_std).to_numpy()
    return (loga - mean) / np.maximum(std, floor)


def row_features(df: pd.DataFrame, L: LearnedStats, cfg: dict, cal: CalendarSpec) -> pd.DataFrame:
    """Calendar, amount, card, relational and context features (index 0..n-1)."""
    n = len(df)
    amt = amount_array(df)
    loga = np.log1p(amt)
    out = calendar_features(
        df["TransactionDT"].to_numpy("int64"),
        cal,
        L.low_volume_start_hour,
        L.local_offset_hours,
        L.season_days,
    )

    # amount
    cents = np.rint(amt * 100).astype("int64")
    ndec = _n_decimals(amt)
    out["amt_log"] = loga
    out["amt_n_decimals"] = ndec
    out["amt_has_3dec"] = ndec == 3
    out["amt_fit_freq"] = pd.Series(cents).map(L.amt_cent_share).fillna(0.0).to_numpy()
    out["amt_is_common"] = np.isin(cents, L.common_cents)
    product = value_keys(get_col(df, "ProductCD")).to_numpy()
    out["amt_vs_product_q"] = _product_quantile(amt, product, L)

    # card age (D1 semantics: K-05)
    d1 = get_col(df, "D1").astype("float64").to_numpy()
    out["card_age_days"] = d1
    out["is_new_card"] = d1 == 0
    out["card_start_day"] = df["TransactionDT"].to_numpy("int64") // 86400 - d1

    # relational
    p_dom, r_dom = get_col(df, "P_emaildomain"), get_col(df, "R_emaildomain")
    has_r = r_dom.notna().to_numpy()
    both = has_r & p_dom.notna().to_numpy()
    mismatch = value_keys(p_dom).to_numpy() != value_keys(r_dom).to_numpy()
    addr2 = get_col(df, "addr2").astype("float64").to_numpy()
    out["has_recipient"] = has_r
    out["email_mismatch"] = both & mismatch
    out["foreign_addr2"] = ~np.isnan(addr2) & (addr2 != L.dominant_addr2)
    out["addr2_missing"] = np.isnan(addr2)
    c1, c2 = cfg["rare_combo"]["columns"]
    present = get_col(df, c1).notna().to_numpy() | get_col(df, c2).notna().to_numpy()
    combo = value_keys(get_col(df, c1)) + "|" + value_keys(get_col(df, c2))
    share = combo.map(L.combo_share).fillna(0.0).to_numpy()
    out["os_browser_rare"] = present & (share < cfg["rare_combo"]["ratio"])

    # context
    if "has_identity" in df.columns:
        out["has_identity"] = df["has_identity"].fillna(False).astype(bool).to_numpy()
    else:
        id_cols = [c for c in df.columns if c.startswith(ID_COLUMNS_HINT)]
        out["has_identity"] = df[id_cols].notna().any(axis=1).to_numpy() if id_cols else False
    for col in ("dist1", "dist2"):
        v = get_col(df, col).astype("float64").to_numpy()
        out[f"{col}_missing"] = np.isnan(v)
        out[f"{col}_log"] = np.log1p(np.clip(v, 0, None))
    floor = cfg["amount"]["group_std_floor"]
    out["amt_dev_card4_card6"] = _group_deviation(
        loga, group_keys(df, "card4_card6"), L.group_stats["card4_card6"], L, floor
    )
    out["amt_dev_addr1"] = _group_deviation(
        loga, group_keys(df, "addr1"), L.group_stats["addr1"], L, floor
    )
    for col in cfg["freq_columns"]:
        out[f"freq_{col}"] = (
            value_keys(get_col(df, col)).map(L.freq_tables[col]).fillna(0.0).to_numpy()
        )
    assert len(out) == n
    return out
