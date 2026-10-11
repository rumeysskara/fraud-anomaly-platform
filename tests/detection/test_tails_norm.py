"""TailScorer, QuantileNormalizer and RobustPreprocessor on small synthetic arrays."""

import numpy as np
import pandas as pd

from src.detection.normalization import QuantileNormalizer
from src.detection.preprocess import RobustPreprocessor
from src.detection.tails import TailScorer

PRE_CFG = {"skew_threshold": 5.0, "clip_quantiles": [0.001, 0.999], "na_flag_min_rate": 0.0}


def test_two_sided_tail_is_larger_in_the_tails():
    x = np.random.default_rng(42).normal(size=5000)
    s = TailScorer("two").fit(x).score(np.array([0.0, 3.0, -3.0, 10.0]))
    assert s[0] < 0.1 < s[1] and abs(s[1] - s[2]) < 0.6
    assert s[3] > s[1]  # beyond the fit range: smoothed, finite
    assert np.isfinite(s).all()


def test_one_sided_modes():
    x = np.arange(1000, dtype=float)
    assert TailScorer("upper").fit(x).score(np.array([999.0]))[0] > 2.5
    assert TailScorer("upper").fit(x).score(np.array([0.0]))[0] == 0.0
    assert TailScorer("lower").fit(x).score(np.array([0.0]))[0] > 2.5


def test_discrete_uses_log_frequency_and_unseen_value():
    x = np.array([0.0] * 90 + [1.0] * 10)
    sc = TailScorer("discrete").fit(x)
    s = sc.score(np.array([0.0, 1.0, 5.0]))
    assert np.isclose(s[1], 1.0) and s[0] < s[1] < s[2]


def test_nan_policy():
    x = np.array([1.0, 2.0, np.nan, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    assert TailScorer("two", "level").fit(x).score(np.array([np.nan]))[0] > 0
    assert TailScorer("two", "zero").fit(x).score(np.array([np.nan]))[0] == 0


def test_normalizer_uniform_ties_and_range():
    rng = np.random.default_rng(42)
    raw = np.concatenate([np.zeros(600), rng.random(400)])
    norm = QuantileNormalizer(1001).fit(raw)
    out = norm.transform(np.array([-5.0, 0.0, 0.5, 99.0]))
    assert (out >= 0).all() and (out <= 1).all()
    assert np.isclose(out[1], 0.3, atol=0.02)  # ties get the mean rank of their block
    assert out[2] > out[1] and out[3] == out[3] and out[3] >= out[2]
    assert np.all(np.diff(norm.xp_) > 0)
    assert len(norm.table_) == 1001


def test_normalizer_constant_input():
    out = QuantileNormalizer(101).fit(np.ones(50)).transform(np.array([1.0, 2.0]))
    assert np.isfinite(out).all()


def test_preprocessor_sentinel_log_clip_and_flags():
    rng = np.random.default_rng(42)
    n = 5000
    heavy = np.exp(rng.normal(0, 3, n))
    df = pd.DataFrame(
        {
            "gap": np.where(rng.random(n) < 0.2, -1.0, rng.normal(100, 10, n)),
            "heavy": heavy,
            "dense": rng.normal(size=n),
        }
    )
    pre = RobustPreprocessor(["gap", "heavy", "dense"], ["gap"], PRE_CFG).fit(df)
    assert "heavy" in pre.log_cols and "dense" not in pre.log_cols
    assert "gap" in pre.na_cols and "dense" not in pre.na_cols
    x = pre.transform(df)
    assert x.dtype == np.float32 and not np.isnan(x).any()
    assert pre.output_columns[-1] == "gap__na"
    assert np.isclose(x[:, 3].mean(), 0.2, atol=0.03)  # sentinel rows flagged
    lo, hi = pre.bounds_["heavy"]
    assert x[:, 1].max() <= hi + 1e-3 and x[:, 1].min() >= lo - 1e-3
    out = pre.transform(pd.DataFrame({"gap": [np.nan], "heavy": [1e12], "dense": [np.nan]}))
    assert not np.isnan(out).any() and out[0, 1] <= hi + 1e-3  # unseen extreme is clipped


def test_preprocessor_refit_does_not_duplicate_lists():
    rng = np.random.default_rng(42)
    n = 2000
    df = pd.DataFrame(
        {
            "gap": np.where(rng.random(n) < 0.2, -1.0, rng.normal(100, 10, n)),
            "heavy": np.exp(rng.normal(0, 3, n)),
        }
    )
    pre = RobustPreprocessor(["gap", "heavy"], ["gap"], PRE_CFG).fit(df)
    first = (list(pre.log_cols), list(pre.na_cols), list(pre.output_columns))
    pre.fit(df)
    assert (pre.log_cols, pre.na_cols, pre.output_columns) == first
    assert pre.transform(df).shape[1] == len(first[2])
