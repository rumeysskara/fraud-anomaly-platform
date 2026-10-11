"""History features use only earlier rows; the first transaction has safe defaults."""

import numpy as np
import pandas as pd

from src.features.utils import entity_keys


def test_first_transaction_defaults(pipe, frame):
    out = pipe.transform(frame)
    key = entity_keys(frame, pipe.entity_columns)
    first = ~key.duplicated().to_numpy()
    f = out[first]
    assert (f["is_first_seen"] == 1).all()
    assert (f["ent_txn_count"] == 0).all()
    assert (f["ent_cnt_7d"] == 0).all() and (f["ent_sum_7d"] == 0).all()
    assert (f["amt_ratio_to_ent_avg"] == 1).all() and (f["amt_zscore_ent"] == 0).all()
    assert (f["time_since_last_txn"] == -1).all() and (f["avg_inter_arrival"] == -1).all()
    assert np.allclose(f["ent_avg_amt"], pipe.stats.amt_mean, rtol=1e-5)
    assert (f["ent_max_amt"] == 0).all() and (f["ent_age_days"] == 0).all()
    assert not out[~first]["is_first_seen"].any()


def test_future_rows_do_not_change_past_features(pipe, frame):
    k = 250
    full = pipe.transform(frame)
    head = pipe.transform(frame.iloc[:k])
    pd.testing.assert_frame_equal(full.iloc[:k], head)
    changed = frame.copy()
    changed.iloc[k:, changed.columns.get_loc("TransactionAmt")] = np.float32(9999)
    again = pipe.transform(changed)
    pd.testing.assert_frame_equal(full.iloc[:k], again.iloc[:k])


def test_current_row_excluded_from_its_own_history(pipe):
    df = pd.DataFrame(
        {
            "TransactionDT": [100, 200, 300],
            "TransactionAmt": np.array([10, 20, 600], dtype="float32"),
            "card1": [1, 1, 1],
            "addr1": [5.0, 5.0, 5.0],
        }
    )
    out = pipe.transform(df)
    assert list(out["ent_txn_count"]) == [0, 1, 2]
    assert out["ent_avg_amt"].iloc[2] == 15.0  # mean of 10 and 20 only
    assert out["ent_max_amt"].iloc[2] == 20.0
    assert out["amt_ratio_to_ent_avg"].iloc[2] == 40.0


def test_window_counts_and_small_streak(pipe):
    pipe.stats.small_amt_threshold = 26.0
    t = [0, 1800, 4000, 4100, 100_000]
    df = pd.DataFrame(
        {
            "TransactionDT": t,
            "TransactionAmt": np.array([5, 7, 500, 9, 9], dtype="float32"),
            "card1": 1,
            "addr1": 5.0,
        }
    )
    out = pipe.transform(df)
    assert list(out["ent_cnt_1h"]) == [
        0,
        1,
        1,
        2,
        0,
    ]  # row 2 at 4000: event at 0 is 4000s old (outside 1h)
    assert list(out["ent_cnt_6h"]) == [0, 1, 2, 3, 0]
    assert list(out["small_amt_streak_1h"]) == [0, 1, 1, 1, 0]
    assert out["ent_sum_6h"].iloc[3] == 512.0
    assert out["ent_cnt_24h"].iloc[4] == 0 and out["ent_cnt_7d"].iloc[4] == 4
