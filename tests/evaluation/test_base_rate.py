"""Base rate tests on a synthetic label."""

import pandas as pd

from src.evaluation.base_rate import label_base_rates


def test_label_base_rates_time_order():
    y = pd.Series([0, 0, 0, 0, 1, 0, 0, 1, 0, 1], dtype="int8")
    out = label_base_rates(y, 0.8).set_index("scope")
    assert out.loc["fit", "n_rows"] == 8 and out.loc["holdout", "n_rows"] == 2
    assert out.loc["fit", "base_rate"] == 0.25
    assert out.loc["holdout", "base_rate"] == 0.5
    assert out.loc["all", "n_positive"] == 3
