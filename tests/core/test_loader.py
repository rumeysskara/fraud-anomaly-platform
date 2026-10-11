"""Loader tests on small synthetic CSVs (no real data)."""

import numpy as np
import pandas as pd
import pytest

from src.core.config import load_settings
from src.data.loader import add_datetime, load_data, split_by_time


@pytest.fixture()
def data_dir(tmp_path):
    n = 20
    rng = np.random.default_rng(0)
    ids = np.arange(1000, 1000 + n)
    trans = pd.DataFrame(
        {
            "TransactionID": ids,
            "isFraud": [1 if i % 10 == 0 else 0 for i in range(n)],
            "TransactionDT": np.arange(n) * 100,  # sorted on disk, like the real file
            "TransactionAmt": rng.random(n) * 100,
        }
    )
    ident = pd.DataFrame({"TransactionID": ids[:5], "DeviceType": ["mobile"] * 5})
    trans.to_csv(tmp_path / "train_transaction.csv", index=False)
    ident.to_csv(tmp_path / "train_identity.csv", index=False)
    return tmp_path


def test_left_join_and_label_separate(data_dir):
    X, y = load_data(data_dir, sample_n=None, settings=load_settings())
    assert len(X) == 20 and len(y) == 20
    assert "isFraud" not in X.columns
    assert X["DeviceType"].notna().sum() == 5
    assert X["TransactionDT"].is_monotonic_increasing
    assert X.index.equals(y.index)
    assert X["TransactionAmt"].dtype == np.float32


def test_sample_n_takes_earliest(data_dir):
    X, y = load_data(data_dir, sample_n=5, settings=load_settings())
    assert len(X) == 5 and X["TransactionDT"].max() == 400


def test_sample_n_filters_identity(data_dir):
    X, _ = load_data(data_dir, sample_n=3, settings=load_settings())
    assert list(X.index) == [1000, 1001, 1002]
    assert X["DeviceType"].notna().all()  # first 3 ids all have identity rows
    X2, _ = load_data(data_dir, sample_n=8, settings=load_settings())
    assert len(X2) == 8 and X2["DeviceType"].notna().sum() == 5
    assert X2.index.is_unique  # filtered identity must not duplicate rows


def test_sample_n_env(data_dir, monkeypatch):
    monkeypatch.setenv("SAMPLE_N", "7")
    X, _ = load_data(data_dir, settings=load_settings())
    assert len(X) == 7


def test_split_by_time(data_dir):
    X, _ = load_data(data_dir, sample_n=None, settings=load_settings())
    shuffled = X.sample(frac=1, random_state=1)
    fit, hold = split_by_time(shuffled)  # ratio from settings.yaml (0.8)
    assert len(fit) == 16 and len(hold) == 4
    assert fit["TransactionDT"].max() < hold["TransactionDT"].min()


def test_reference_date():
    df = pd.DataFrame({"TransactionDT": [0, 86400]})
    dt = add_datetime(df)  # reference date from settings.yaml
    assert dt.iloc[1] == pd.Timestamp("2017-12-02")
