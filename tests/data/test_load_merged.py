"""load_merged tests on small synthetic CSVs."""

import numpy as np
import pandas as pd
import pytest

from src.core.config import load_settings
from src.data.loader import load_merged


@pytest.fixture()
def data_dir(tmp_path):
    n = 30
    ids = np.arange(500, 500 + n)
    trans = pd.DataFrame(
        {
            "TransactionID": ids,
            "isFraud": [i % 7 == 0 for i in range(n)],
            "TransactionDT": np.arange(n) * 60,
            "TransactionAmt": np.linspace(5, 100, n),
            "ProductCD": ["W", "C"] * (n // 2),
        }
    )
    trans["isFraud"] = trans["isFraud"].astype(int)
    trans.to_csv(tmp_path / "train_transaction.csv", index=False)
    ident = pd.DataFrame({"TransactionID": ids[::3], "id_01": -5.0, "DeviceType": "mobile"})
    ident.to_csv(tmp_path / "train_identity.csv", index=False)
    return tmp_path


def test_left_join_keeps_all_transactions(data_dir):
    X, y, stats = load_merged(data_dir=data_dir, sample_n=None, settings=load_settings())
    assert len(X) == 30 == stats["rows_after_join"]
    assert stats["matched_rows"] == 10 == X["has_identity"].sum()
    assert X.index.name == "TransactionID"


def test_label_is_separate_and_dtypes_downcast(data_dir):
    X, y, _ = load_merged(data_dir=data_dir, sample_n=None, settings=load_settings())
    assert "isFraud" not in X.columns
    assert y.index.equals(X.index)
    assert X["id_01"].dtype == np.float32
    assert isinstance(X["ProductCD"].dtype, pd.CategoricalDtype)


def test_sample_n_takes_earliest_rows(data_dir):
    X, _, stats = load_merged(data_dir=data_dir, sample_n=12, settings=load_settings())
    assert len(X) == 12
    assert X["TransactionDT"].is_monotonic_increasing
    assert stats["identity_rows_in_scope"] == 4
