"""Outlier, distribution, rare-category and relation tests."""

import numpy as np
import pandas as pd

from src.profiling import distributions, relations, schema
from src.profiling.config import profiling_config


def test_outlier_row_detects_spike():
    s = pd.Series(list(np.arange(100) % 11 + 5.0) + [1000.0])
    row = distributions.outlier_row("x", s)
    assert row["n_iqr_outliers"] >= 1
    assert row["n_robust_z_outliers"] >= 1


def test_outlier_row_zero_mad():
    row = distributions.outlier_row("x", pd.Series([1.0] * 20 + [50.0]))
    assert row["mad_is_zero"] and "n_robust_z_outliers" not in row


def test_outlier_table_adds_log_row(frame):
    tbl = distributions.outlier_table(frame, ["V3"])
    assert "TransactionAmt__log1p" in set(tbl["column"])


def test_numeric_distributions_and_topn(frame):
    d = distributions.numeric_distributions(frame, ["V3", "C1"])
    assert {"skew", "kurtosis", "q50", "q99"} <= set(d.columns)
    top = distributions.categorical_topn(frame, ["ProductCD"], n=2)
    assert len(top) == 2 and top["ratio"].sum() <= 1.0


def test_rare_combinations():
    df = pd.DataFrame({"a": ["x"] * 99 + ["y"], "b": ["u"] * 100})
    cfg = {**profiling_config("rare"), "rare_ratio": 0.05}
    detail, summary = distributions.rare_combinations(df, [["a", "b"]], cfg)
    assert summary.loc[0, "n_rare"] == 1
    assert detail.loc[0, "values"] == "y | u"


def test_spearman_and_clusters(frame):
    sch = schema.infer_schema(frame, time_col="TransactionDT")
    cfg = {**profiling_config("relations"), "spearman_min_abs": 0.9, "spearman_min_periods": 20}
    pairs = relations.spearman_pairs(frame, ["V1", "V2", "V3"], 42, cfg)
    assert {("V1", "V2")} == set(zip(pairs["col_a"], pairs["col_b"], strict=True))
    clusters = relations.redundancy_clusters(pairs, sch)
    assert set(clusters["column"]) == {"V1", "V2"}
    assert clusters["representative"].nunique() == 1


def test_cramers_v():
    a = pd.Series(list("xyxyxyxyxy") * 10)
    assert relations.cramers_v(a, a) > 0.9
    rng = np.random.default_rng(0)
    b = pd.Series(rng.choice(list("uv"), 100))
    c = pd.Series(rng.choice(list("pq"), 100))
    assert relations.cramers_v(b, c) < 0.3


def test_config_is_single_source():
    cfg = profiling_config("outliers")
    loose = {**cfg, "iqr_k": 1000.0, "robust_z_cut": 1e6}
    s = pd.Series(list(np.arange(100) % 11 + 5.0) + [1000.0])
    assert distributions.outlier_row("x", s, loose)["n_iqr_outliers"] == 0
    assert distributions.outlier_row("x", s)["n_iqr_outliers"] >= 1
