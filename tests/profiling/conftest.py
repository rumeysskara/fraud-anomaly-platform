"""Shared synthetic frame for profiling tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def frame() -> pd.DataFrame:
    """Time-sorted synthetic frame mimicking the IEEE-CIS column groups."""
    rng = np.random.default_rng(42)
    n = 400
    df = pd.DataFrame(
        {
            "TransactionDT": np.arange(n) * 3600,
            "TransactionAmt": np.round(rng.lognormal(3, 1, n), 2).astype("float32"),
            "ProductCD": rng.choice(["W", "C", "H"], n),
            "card1": rng.integers(1000, 1040, n),
            "card2": rng.choice([100.0, 200.0, np.nan], n),
            "addr1": rng.choice([10.0, 20.0, np.nan], n, p=[0.45, 0.45, 0.1]),
            "C1": rng.integers(0, 50, n).astype("float32"),
            "V1": rng.normal(size=n).astype("float32"),
            "M1": rng.choice(["T", "F"], n),
            "const": 7,
        }
    )
    df["V2"] = (df["V1"] * 2).astype("float32")  # redundant with V1
    df["V3"] = rng.normal(size=n).astype("float32")
    df.loc[df.index % 5 == 0, ["V1", "V2"]] = np.nan
    df["has_identity"] = df.index % 3 == 0
    df.index = pd.Index(np.arange(9000, 9000 + n), name="TransactionID")
    df["ProductCD"] = df["ProductCD"].astype("category")
    df["M1"] = df["M1"].astype("category")
    return df
