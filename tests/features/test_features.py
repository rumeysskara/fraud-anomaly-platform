"""Calendar, amount, relational and context features plus catalog consistency."""

import numpy as np
import pandas as pd
import pytest

from src.features.config_io import MARKER, write_learned_block
from src.features.learned import passthrough_columns
from src.features.timecal import hourly_counts, lowest_window_start


def test_low_volume_window_is_argmin(pipe, frame):
    counts = np.array([5] * 24)
    counts[[7, 8, 9, 10, 11, 12]] = 1
    assert lowest_window_start(counts, 6) == 7
    counts = np.array([5] * 24)
    counts[[22, 23, 0, 1, 2, 3]] = 1  # wraps around midnight
    assert lowest_window_start(counts, 6) == 22
    assert pipe.stats.local_offset_hours == -pipe.stats.low_volume_start_hour
    assert sum(hourly_counts(frame["TransactionDT"].to_numpy(), pipe.calendar.ref_seconds)) == len(
        frame
    )


def test_calendar_values(pipe):
    ref_day = 24 * 86400  # 2017-12-25 00:00 on the reference clock (Monday)
    start = pipe.stats.low_volume_start_hour
    df = pd.DataFrame(
        {
            "TransactionDT": [
                ref_day + start * 3600,
                ref_day + (start + 12) * 3600,
                30 * 86400,
                36 * 86400,
            ],
            "TransactionAmt": np.float32(10),
            "card1": 1,
        }
    )
    # season = 2017-12-19 .. 2017-12-26 (as if learned): day 24 inside, day 30 and 36 outside
    pipe.stats.season = {"start_day": 17519, "end_day": 17526}
    o = pipe.transform(df)
    assert list(o["is_holiday"]) == [1, 1, 0, 0]  # Dec 25; Dec 31 and Jan 6 are not holidays
    assert list(o["holiday_season"]) == [1, 1, 0, 0]  # learned window, not the old Dec 20 - Jan 2
    assert o["days_to_nearest_holiday"].iloc[2] == 1  # Dec 31 -> Jan 1
    assert o["day_of_week"].iloc[0] == 0 and o["is_weekend"].iloc[0] == 0
    assert o["is_low_volume_window"].iloc[0] == 1 and o["local_hour_est"].iloc[0] == 0
    assert o["local_hour_est"].iloc[1] == 12 and o["is_low_volume_window"].iloc[1] == 0
    assert o["is_business_hours"].iloc[1] == 1 and o["is_business_hours"].iloc[0] == 0


def test_weekend_uses_reference_calendar(pipe):
    sat = 5 * 86400 + 3600  # 2017-12-06 is Wed; +5d -> Dec 11? check by day_of_week below
    df = pd.DataFrame({"TransactionDT": [sat], "TransactionAmt": np.float32(1), "card1": 1})
    o = pipe.transform(df)
    expected = pd.Timestamp("2017-12-01") + pd.Timedelta(seconds=sat)
    assert o["day_of_week"].iloc[0] == expected.dayofweek
    assert bool(o["is_weekend"].iloc[0]) == (expected.dayofweek >= 5)


def test_relational_flags(pipe):
    df = pd.DataFrame(
        {
            "TransactionDT": [1, 2, 3, 4],
            "TransactionAmt": np.float32(10),
            "card1": 1,
            "P_emaildomain": ["a.com", "a.com", None, "a.com"],
            "R_emaildomain": ["b.com", "a.com", "b.com", None],
            "addr2": [87.0, 60.0, np.nan, 87.0],
        }
    )
    o = pipe.transform(df)
    assert list(o["has_recipient"]) == [1, 1, 1, 0]
    assert list(o["email_mismatch"]) == [1, 0, 0, 0]  # only when both present
    assert list(o["foreign_addr2"]) == [0, 1, 0, 0]
    assert list(o["addr2_missing"]) == [0, 0, 1, 0]


def test_amount_features(pipe):
    df = pd.DataFrame(
        {
            "TransactionDT": [1, 2, 3],
            "TransactionAmt": np.array([10.0, 12.345, 31.5], dtype="float32"),
            "card1": [1, 2, 3],
        }
    )
    o = pipe.transform(df)
    assert list(o["amt_n_decimals"]) == [0, 3, 1]
    assert list(o["amt_has_3dec"]) == [0, 1, 0]
    assert o["amt_fit_freq"].iloc[1] == 0  # unseen amount
    assert o["amt_vs_product_q"].between(0, 1).all()


def test_catalog_matches_output(pipe, frame):
    out = pipe.transform(frame)
    cat = pipe.catalog
    assert list(out.columns) == list(cat["name"])
    assert cat["name"].is_unique
    counts = cat["group"].value_counts()
    assert counts["temporal"] >= 4 and counts["entity"] >= 6
    assert counts["relational"] >= 4 and counts["context"] >= 4
    assert "isFraud" not in out.columns
    assert not (out.dtypes == "float64").any()  # memory: everything downcast


def test_one_row_has_all_catalog_columns(pipe, frame):
    from tests.features.conftest import to_txn

    o = pipe.transform_one(to_txn(frame.iloc[0]))
    assert list(o) == list(pipe.catalog["name"])


def test_passthrough_uses_cluster_representatives():
    clusters = pd.DataFrame(
        {"column": ["V1", "V2", "C8", "C10"], "representative": ["V1", "V1", "C10", "C10"]}
    )
    cfg = {"groups": ["V", "C", "D"], "exclude": ["D1"]}
    cols = ["V1", "V2", "V3", "C8", "C10", "D1", "D4", "card1"]
    assert passthrough_columns(cols, cfg, clusters) == ["V1", "V3", "C10", "D4"]


def test_write_learned_block_is_idempotent(tmp_path):
    p = tmp_path / "entity.yaml"
    p.write_text("# comment\nentity:\n  name: x\n", encoding="utf-8")
    write_learned_block(p, {"a": 1})
    write_learned_block(p, {"a": 2})
    text = p.read_text(encoding="utf-8")
    assert text.count(MARKER) == 1 and "a: 2" in text and "# comment" in text


def test_detect_season_finds_multi_day_peak_and_ignores_spike():
    from src.features.timecal import detect_season

    rng = np.random.default_rng(0)
    counts = rng.integers(95, 105, 120)
    counts[30:38] = 150  # 8-day peak (1.5x)
    counts[80] = 400  # one-day spike: shorter than min_days
    dt = np.concatenate([np.full(c, d * 86400 + 10) for d, c in enumerate(counts)])
    cfg = {"baseline_days": 29, "ratio_threshold": 1.25, "min_days": 3}
    window, table = detect_season(dt, 0, cfg)
    assert (window["start_day"], window["end_day"]) == (30, 37)
    assert 1.4 < window["mean_ratio"] < 1.6
    assert table["in_window"].sum() == 8
    # a 7-day baseline cannot see the 8-day peak (its own median is raised)
    short, _ = detect_season(dt, 0, {**cfg, "baseline_days": 7})
    assert short is None or short["end_day"] - short["start_day"] < 7


def test_no_season_when_volume_is_flat(pipe):
    from src.features.timecal import detect_season

    dt = np.repeat(np.arange(60) * 86400, 50)
    window, _ = detect_season(dt, 0, pipe.config["holidays"]["season"])
    assert window is None


def test_model_input_flag_in_catalog(pipe):
    cat = pipe.catalog
    off = set(cat.loc[~cat["model_input"], "name"])
    assert off == {"is_holiday", "days_to_nearest_holiday"}
    assert cat["model_input"].dtype == bool
    assert (cat.loc[~cat["model_input"], "model_input_note"] != "").all()
    assert "holiday_season" in pipe.model_input_columns
    assert "is_holiday" not in pipe.model_input_columns
    assert len(pipe.model_input_columns) == len(cat) - 2


def _synthetic_season_dt():
    rng = np.random.default_rng(0)
    counts = rng.integers(95, 105, 120)
    counts[30:38] = 150
    return np.concatenate([np.full(c, d * 86400 + 10) for d, c in enumerate(counts)])


def test_season_window_stable_across_threshold_sweep():
    from src.features.reports import season_threshold_sensitivity

    cfg = {
        "baseline_days": 29,
        "ratio_threshold": 1.25,
        "min_days": 3,
        "sensitivity": {"min": 1.20, "max": 1.30, "step": 0.01},
    }
    table = season_threshold_sensitivity(_synthetic_season_dt(), 0, cfg)
    assert len(table) == 11
    assert table["same_as_selected"].all()
    assert table["n_days"].eq(8).all()


def test_small_streak_window_must_be_a_velocity_window(pipe, frame):
    from src.features.history import small_streak_name

    assert small_streak_name(pipe.config) == "small_amt_streak_1h"
    bad = {**pipe.config, "small_amount": {**pipe.config["small_amount"], "window": "30d"}}
    with pytest.raises(ValueError, match="velocity window"):
        small_streak_name(bad)
    pipe.config = bad
    with pytest.raises(ValueError):
        pipe.transform(frame)


def test_small_streak_follows_configured_window(pipe):
    cfg = {**pipe.config, "small_amount": {**pipe.config["small_amount"], "window": "6h"}}
    pipe.config = cfg
    pipe.stats.small_amt_threshold = 26.0
    df = pd.DataFrame(
        {
            "TransactionDT": [0, 1800, 4000, 100_000],
            "TransactionAmt": np.array([5, 7, 500, 9], dtype="float32"),
            "card1": 1,
            "addr1": 5.0,
        }
    )
    out = pipe.transform(df)
    assert "small_amt_streak_6h" in out.columns and "small_amt_streak_1h" not in out.columns
    assert list(out["small_amt_streak_6h"]) == [0, 1, 2, 0]
    assert (
        pipe.transform_one(
            {"TransactionDT": 100_100, "TransactionAmt": 5.0, "card1": 1, "addr1": 5.0}
        )["small_amt_streak_6h"]
        == 0
    )
