"""D1 semantics tests on synthetic data where the true meaning is known."""

import numpy as np
import pandas as pd

from src.profiling import d1_semantics as d1s

DAY = 86400


def test_previous_day_gap():
    key = np.array([0, 1, 0, 1, 0, -1])
    day = np.array([1.0, 2.0, 4.0, 2.0, 9.0, 5.0])
    gap = d1s.previous_day_gap(key, day)
    assert np.isnan(gap[0]) and np.isnan(gap[1]) and np.isnan(gap[5])
    assert gap[2] == 3 and gap[3] == 0 and gap[4] == 5


def test_permute_within_keeps_multiset_per_entity():
    key = np.array([0, 0, 0, 1, 1, 2])
    vals = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 5.0])
    out = d1s.permute_within(key, vals, 42)
    assert sorted(out[:3]) == [1.0, 2.0, 3.0] and sorted(out[3:5]) == [10.0, 20.0]
    assert out[5] == 5.0
    assert np.array_equal(out, d1s.permute_within(key, vals, 42))  # seeded


def test_seen_before_rate():
    key = np.array([0, 0, 0, 1])
    start = np.array([5.0, 5.0, 6.0, 5.0])
    mask = np.ones(4, dtype=bool)
    assert d1s.seen_before_rate(key, start, mask) == 0.25  # only row 1 repeats


def _frame(card_age: bool) -> pd.DataFrame:
    """One card with 40 transactions on distinct days; D1 is either card age or gap."""
    n = 40
    day = np.arange(n) * 2 + 10
    d1 = day - 3 if card_age else np.r_[np.nan, np.diff(day)]
    return pd.DataFrame(
        {
            "TransactionDT": day * DAY,
            "card1": 1,
            "addr1": 100.0,
            "D1": d1,
        }
    )


def test_gap_hypothesis_detected():
    out = d1s.d1_semantics(_frame(card_age=False), "TransactionDT", 42).set_index("metric")
    assert out.loc["A_prev_gap_matches_D1", "value"] == 1.0
    assert out.loc["B_pair_seen_before[all_D1_rows]", "value"] < 0.1  # D1n keeps changing


def test_card_age_hypothesis_detected():
    out = d1s.d1_semantics(_frame(card_age=True), "TransactionDT", 42).set_index("metric")
    assert out.loc["B_pair_seen_before[all_D1_rows]", "value"] > 0.9  # D1n constant = 3 + ...
    assert out.loc["A_prev_gap_matches_D1", "value"] < 0.2
