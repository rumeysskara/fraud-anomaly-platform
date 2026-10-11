"""EDA helper and chart tests on synthetic data."""

import numpy as np
import pandas as pd

from src.profiling import eda
from src.profiling import eda_figures as figs

REF = pd.Timestamp("2017-12-01")


def _counts() -> pd.Series:
    """120 days: weekly pattern (Mondays low), a peak on days 18-25 and a spike on day 92."""
    idx = pd.date_range(REF, periods=120, freq="D")
    base = np.where(idx.dayofweek == 0, 80, 100).astype(float)
    base[18:26] *= 2
    base[92] *= 3
    return pd.Series(base, index=idx, name="n")


def test_value_share_marks_missing():
    out = eda.value_share(pd.Series(["a", "a", "b", None]), n=2)
    assert list(out["value"]) == ["a", "b"] or list(out["value"])[1] in ("b", eda.MISSING)
    assert out["share"].iloc[0] == 0.5


def test_daily_counts_zero_fills():
    dt = pd.Series(pd.to_datetime(["2017-12-01 10:00", "2017-12-01 11:00", "2017-12-04 01:00"]))
    c = eda.daily_counts(dt)
    assert list(c) == [2, 0, 0, 1]


def test_autocorrelation_peaks_at_lag_7():
    acf = eda.autocorrelation(_counts().iloc[40:90]).set_index("lag")
    assert acf.loc[7, "acf_detrended"] > 0.5
    assert acf.loc[7, "acf_detrended"] > acf.loc[3, "acf_detrended"]


def test_peak_and_spike_stats():
    counts = _counts()
    assert eda.best_peak_window(counts, REF) == (18, 25)
    w = eda.window_stats(counts, 18, 25, REF)
    assert w["ratio_inside_vs_surround"] > 1.5 and w["start_date"] == "2017-12-19"
    s = eda.spike_stats(counts, REF)
    assert s["date"] == "2018-03-03" and s["ratio_vs_previous_day"] > 2.5
    assert abs(s["level_shift_next7_vs_prior7"] - 1) < 0.1  # one-day spike, no level shift


def test_top_amounts_rounds_float32_noise():
    amt = pd.Series([107.95, 107.95, 59.0], dtype="float32")
    out = eda.top_amounts(amt, {**eda.eda_config(), "top_amounts": 2})
    assert out.loc[0, "amount"] == 107.95 and out.loc[0, "n"] == 2


def test_group_builders():
    s = pd.Series(list("aaabbc") + [None])
    g = eda.category_groups(s, n=2)
    assert list(g.cat.categories)[:2] == ["a", "b"] and (g == eda.OTHER).sum() == 1
    assert (g == eda.MISSING).sum() == 1
    dec = eda.decile_groups(pd.Series(np.arange(1.0, 101.0)))
    assert dec.nunique() == 10 and str(dec.iloc[0]).startswith("D1 ")
    d1 = eda.d1_zero_groups(pd.Series([0, 5, np.nan]))
    assert list(d1.astype(str)) == ["D1=0 (yeni kart)", "D1>0", eda.MISSING]
    grp, mode = eda.dominant_value_groups(pd.Series([87.0, 87.0, 60.0, np.nan]))
    assert mode == 87.0 and list(grp.astype(str)) == [
        "baskın (87)",
        "baskın (87)",
        "diğer",
        eda.MISSING,
    ]
    p = pd.Series(["x", "x", "y", None])
    r = pd.Series(["x", "z", None, "x"])
    m = eda.email_match_groups(p, r)
    assert list(m.astype(str)) == [
        "P = R (ikisi dolu)",
        "P != R (ikisi dolu)",
        "yalnız P dolu (R eksik)",
        "P eksik",
    ]


def test_figures_written(tmp_path):
    counts = _counts()
    share = eda.value_share(pd.Series(list("aabbbc")))
    figs.bar_share(share, "value", "t", "x", tmp_path / "s.png")
    rate = pd.DataFrame(
        {
            "group": ["a", "b"],
            "n": [500, 20],
            "fraud_rate": [0.05, 0.0],
            "ci_low": [0.04, 0.0],
            "ci_high": [0.06, 0.15],
            "small_n": [False, True],
        }
    )
    figs.bar_rate(rate, "group", 0.03, "t", "x", tmp_path / "r.png")
    figs.bar_rate(rate, "group", 0.03, "t", "x", tmp_path / "rv.png", vertical=True)
    figs.line_acf(eda.autocorrelation(counts), 7, "t", tmp_path / "a.png")
    figs.daily_volume(counts, [(18, 25, "w")], 92, REF, "t", tmp_path / "d.png")
    figs.bar_amounts(eda.top_amounts(pd.Series([1.0, 1.0, 2.0])), "t", tmp_path / "m.png")
    assert len(list(tmp_path.glob("*.png"))) == 6


def test_eda_constants_come_from_config():
    cfg = eda.eda_config()
    assert cfg["spike_day"] == 92 and cfg["min_n_flag"] == 100 and cfg["week_days"] == 7
    acf = eda.autocorrelation(_counts(), {**cfg, "acf_min_lag": 2, "acf_max_lag": 5})
    assert list(acf["lag"]) == [2, 3, 4, 5]
    s = eda.spike_stats(_counts(), REF, {**cfg, "spike_day": 18})
    assert s["spike_day"] == 18 and s["date"] == "2017-12-19"
    dec = eda.decile_groups(pd.Series(np.arange(1.0, 101.0)), {**cfg, "decile_count": 4})
    assert dec.nunique() == 4
