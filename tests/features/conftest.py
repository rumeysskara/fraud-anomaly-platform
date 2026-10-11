"""Synthetic frames for feature tests (no real data)."""

import numpy as np
import pandas as pd
import pytest

from src.features import FeaturePipeline


def make_frame(n: int = 400, seed: int = 42) -> pd.DataFrame:
    """Time-sorted frame with repeated entities, ties in time and NaNs."""
    rng = np.random.default_rng(seed)
    dt = np.sort(rng.integers(0, 6 * 86400, n))
    dt[10] = dt[9]  # a tie in time
    df = pd.DataFrame(
        {
            "TransactionDT": dt,
            "TransactionAmt": np.round(rng.lognormal(3.5, 1.0, n), 2).astype("float32"),
            "ProductCD": rng.choice(["W", "C", "H"], n),
            "card1": rng.integers(1000, 1012, n),
            "card4": rng.choice(["visa", "mastercard", None], n),
            "card6": rng.choice(["debit", "credit"], n),
            "addr1": rng.choice([10.0, 20.0, np.nan], n, p=[0.45, 0.45, 0.1]),
            "addr2": rng.choice([87.0, 60.0, np.nan], n, p=[0.8, 0.1, 0.1]),
            "dist1": rng.choice([5.0, 120.0, np.nan], n).astype("float32"),
            "P_emaildomain": rng.choice(["gmail.com", "yahoo.com", None], n),
            "R_emaildomain": rng.choice(["gmail.com", "yahoo.com", None, None], n),
            "DeviceInfo": rng.choice(["dev_a", "dev_b", None, None], n),
            "id_30": rng.choice(["Windows 10", "iOS 11", None], n),
            "id_31": rng.choice(["chrome 63", "safari", None], n),
            "id_33": rng.choice(["1920x1080", None], n),
            "D1": rng.choice([0.0, 5.0, 30.0, np.nan], n).astype("float32"),
            "C1": rng.integers(0, 5, n).astype("float32"),
            "V1": rng.normal(size=n).astype("float32"),
            "V2": rng.normal(size=n).astype("float32"),
        }
    )
    df["has_identity"] = df["DeviceInfo"].notna()
    df.index = pd.RangeIndex(5000, 5000 + n, name="TransactionID")
    return df


@pytest.fixture()
def frame() -> pd.DataFrame:
    return make_frame()


@pytest.fixture()
def pipe(frame) -> FeaturePipeline:
    """Pipeline fitted on the first 60% of the synthetic frame."""
    p = FeaturePipeline.from_config()
    return p.fit(frame.iloc[: int(len(frame) * 0.6)], clusters=None)


def to_txn(row: pd.Series) -> dict:
    """Row -> plain dict like an API payload (NaN -> None)."""
    return {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
