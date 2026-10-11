"""drop_cumulative must cover every lifetime-cumulative feature (synthetic stream, no real data)."""

import numpy as np
import pandas as pd

from src.detection.config import load_anomaly_config
from src.features import FeaturePipeline

DAY = 86400
SHIFT_LIMIT = 0.5  # |mean(2nd half) - mean(1st half)| / std(1st half), in first-half stds
N_ROWS, N_DAYS, N_ENTITIES = 6000, 60, 20


def stationary_stream(seed: int = 42) -> pd.DataFrame:
    """Same entities, same behaviour, constant rate: only lifetime-cumulative features can drift."""
    rng = np.random.default_rng(seed)
    n = N_ROWS
    df = pd.DataFrame(
        {
            "TransactionDT": np.sort(rng.integers(0, N_DAYS * DAY, n)),
            "TransactionAmt": np.round(rng.lognormal(3.5, 1.0, n), 2).astype("float32"),
            "ProductCD": rng.choice(["W", "C", "H"], n),
            "card1": rng.integers(1000, 1000 + N_ENTITIES, n),
            "card4": rng.choice(["visa", "mastercard"], n),
            "card6": rng.choice(["debit", "credit"], n),
            "addr1": rng.choice([10.0, 20.0], n),
            "addr2": np.full(n, 87.0),
            "dist1": rng.choice([5.0, 120.0], n).astype("float32"),
            "P_emaildomain": rng.choice([f"mail{i}.com" for i in range(40)], n),
            "R_emaildomain": rng.choice(["gmail.com", None], n),
            "DeviceInfo": rng.choice([f"dev{i}" for i in range(60)], n),
            "id_30": rng.choice(["Windows 10", "iOS 11"], n),
            "id_31": rng.choice(["chrome 63", "safari"], n),
            "id_33": rng.choice(["1920x1080", None], n),
            "D1": rng.choice([0.0, 5.0, 30.0], n).astype("float32"),
            "C1": rng.integers(0, 5, n).astype("float32"),
            "V1": rng.normal(size=n).astype("float32"),
        }
    )
    df["has_identity"] = df["DeviceInfo"].notna()
    df.index = pd.RangeIndex(1, n + 1, name="TransactionID")
    return df


def drifting(features: pd.DataFrame, columns: list[str]) -> set[str]:
    """Columns whose mean moves more than SHIFT_LIMIT first-half stds between the halves."""
    half = len(features) // 2
    out = set()
    for col in columns:
        x = features[col].astype("float64")
        first, second = x.iloc[:half], x.iloc[half:]
        if first.std() > 0 and abs(second.mean() - first.mean()) / first.std() > SHIFT_LIMIT:
            out.add(col)
    return out


def test_drop_lists_cover_every_drifting_model_input():
    common = load_anomaly_config()["common"]
    dropped = set(common["drop_always"]) | set(common["drop_cumulative"])
    frame = stationary_stream()
    pipe = FeaturePipeline.from_config().fit(
        frame, clusters=None
    )  # fit on all: no fit/holdout artefact
    feats = pipe.transform(frame)
    cols = [
        c
        for c in pipe.model_input_columns
        if not c.startswith("V") and pd.api.types.is_numeric_dtype(feats[c])
    ]
    uncovered = drifting(feats, cols) - dropped
    assert (
        not uncovered
    ), f"drifts like a lifetime-cumulative column but is not dropped: {sorted(uncovered)}"


def test_drop_columns_are_real_features():
    """A typo in the config would silently drop nothing."""
    common = load_anomaly_config()["common"]
    frame = stationary_stream()
    pipe = FeaturePipeline.from_config().fit(frame, clusters=None)
    names = set(pipe.catalog["name"])
    assert (set(common["drop_always"]) | set(common["drop_cumulative"])) <= names
