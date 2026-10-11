"""Report tables for Step 3 (label-free sanity checks)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.timecal import CalendarSpec, calendar_features, detect_season, epoch_day_to_date


def _ratio_row(name: str, daily: pd.DataFrame, mask: pd.Series) -> dict:
    """Mean daily volume inside `mask` days vs all other days."""
    inside, outside = daily.loc[mask, "n"], daily.loc[~mask, "n"]
    return {
        "group": name,
        "n_days": int(mask.sum()),
        "mean_daily_txn": float(inside.mean()),
        "mean_daily_txn_other_days": float(outside.mean()),
        "ratio": float(inside.mean() / outside.mean()),
    }


def holiday_volume_check(
    dt: np.ndarray,
    cal: CalendarSpec,
    season: tuple[int, int] | None,
    fixed_window: tuple[str, str] | None = None,
) -> pd.DataFrame:
    """Daily volume on holidays / learned season / old fixed window vs other days (fit, no label).

    The last (partial) fit day is dropped. Ratio = mean daily volume inside / mean outside.
    """
    dt = np.asarray(dt, dtype="int64")
    f = calendar_features(dt, cal, 0, 0, season)
    days = (cal.ref_seconds + dt) // 86400
    frame = pd.DataFrame(
        {"day": days, "hol": f["is_holiday"].to_numpy(), "sea": f["holiday_season"].to_numpy()}
    )
    daily = frame.groupby("day").agg(n=("day", "size"), hol=("hol", "max"), sea=("sea", "max"))
    daily = daily.iloc[:-1]
    rows = []
    if season:
        rows.append(_ratio_row("season_learned", daily, daily["sea"]))
    if fixed_window:
        lo, hi = ((pd.Timestamp(d) - pd.Timestamp(0)).days for d in fixed_window)
        rows.append(
            _ratio_row("season_fixed_old", daily, (daily.index >= lo) & (daily.index <= hi))
        )
    if daily["hol"].sum():
        rows.append(_ratio_row("is_holiday", daily, daily["hol"]))
    out = pd.DataFrame(rows)
    if season:
        out["window"] = ""
        out.loc[out["group"] == "season_learned", "window"] = (
            f"{epoch_day_to_date(season[0])} .. {epoch_day_to_date(season[1])}"
        )
    return out


def season_detection_table(table: pd.DataFrame) -> pd.DataFrame:
    """Daily volume / baseline / ratio / in_window table with ISO dates (for the report)."""
    out = table.copy()
    out.insert(0, "date", [epoch_day_to_date(d) for d in out.index])
    return out.reset_index(drop=True)


def feature_summary(features: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    """Per feature: group, model_input, dtype, null share, mean, min, max."""
    desc = pd.DataFrame(
        {
            "dtype": features.dtypes.astype(str),
            "null_share": features.isna().mean(),
            "mean": features.mean(),
            "min": features.min(),
            "max": features.max(),
        }
    )
    return catalog.set_index("name")[["group", "model_input"]].join(desc).reset_index()


def season_threshold_sensitivity(dt: np.ndarray, ref_seconds: int, cfg: dict) -> pd.DataFrame:
    """Season window found for each ratio threshold in the configured sweep (fit volume only).

    `same_as_selected` compares each window with the one found at cfg["ratio_threshold"].
    """
    sweep = cfg["sensitivity"]
    n = int(round((sweep["max"] - sweep["min"]) / sweep["step"])) + 1
    thresholds = [round(sweep["min"] + i * sweep["step"], 4) for i in range(n)]
    selected, _ = detect_season(dt, ref_seconds, cfg)
    rows = []
    for tau in thresholds:
        window, _ = detect_season(dt, ref_seconds, {**cfg, "ratio_threshold": tau})
        rows.append(
            {
                "ratio_threshold": tau,
                "start_date": epoch_day_to_date(window["start_day"]) if window else "",
                "end_date": epoch_day_to_date(window["end_day"]) if window else "",
                "n_days": window["n_days"] if window else 0,
                "mean_ratio": round(window["mean_ratio"], 3) if window else float("nan"),
                "same_as_selected": bool(
                    window
                    and selected
                    and (window["start_day"], window["end_day"])
                    == (selected["start_day"], selected["end_day"])
                ),
            }
        )
    return pd.DataFrame(rows)
