"""Synthetic feature frames for the detection / scoring tests (no real data)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detection.config import load_anomaly_config, load_weights


def make_features(n: int = 600, seed: int = 42) -> pd.DataFrame:
    """Time-ordered feature-like frame with repeated entities and past-only entity statistics."""
    rng = np.random.default_rng(seed)
    cfg = load_anomaly_config()
    keys = rng.choice([f"k{i}" for i in range(12)], n)
    amt = np.round(rng.lognormal(3.5, 1.0, n), 2)
    t = np.sort(rng.integers(0, 5 * 86400, n))
    rows = []
    hist: dict[str, list[tuple[int, float]]] = {}
    for i in range(n):
        past = hist.setdefault(keys[i], [])
        amts = np.array([a for _, a in past])
        cnt = len(past)
        avg = amts.mean() if cnt else 30.0
        std = amts.std() if cnt >= 2 else 50.0
        gap = t[i] - past[-1][0] if cnt else -1
        mean_gap = (past[-1][0] - past[0][0]) / (cnt - 1) if cnt >= 2 else -1
        rows.append(
            {
                "ent_txn_count": cnt,
                "ent_avg_amt": avg,
                "ent_std_amt": std,
                "amt_ratio_to_ent_avg": amt[i] / avg,
                "time_since_last_txn": gap,
                "avg_inter_arrival": mean_gap,
                "ent_cnt_1h": sum(1 for d, _ in past if d >= t[i] - 3600),
                "ent_cnt_24h": sum(1 for d, _ in past if d >= t[i] - 86400),
                "ent_sum_1h": sum(a for d, a in past if d >= t[i] - 3600),
            }
        )
        past.append((int(t[i]), float(amt[i])))
    df = pd.DataFrame(rows)
    df["amt_log"] = np.log1p(amt)
    df["hour"] = (t // 3600) % 24
    df["day_of_week"] = (t // 86400) % 7
    df["is_low_volume_window"] = ((df["hour"] >= 6) & (df["hour"] < 12)).astype(int)
    df["device_ent_match"] = rng.integers(0, 3, n)
    df["freq_DeviceInfo"] = rng.choice([0.5, 0.05, 0.001], n)
    df["card_new_addr"] = (df["ent_txn_count"] == 0) & (rng.random(n) < 0.3)
    df["card_new_addr"] = df["card_new_addr"].astype(int)
    df["day_index"] = t // 86400
    df["V1"] = rng.normal(size=n)
    for col in cfg["column"]["columns"]:
        if col not in df.columns:
            df[col] = rng.normal(size=n) if rng.random() < 0.7 else rng.integers(0, 3, n)
    df["C13"] = rng.poisson(2, n).astype(float)
    df["D4"] = np.where(rng.random(n) < 0.3, np.nan, rng.exponential(10, n))
    df["entity_key"] = keys
    df["has_device"] = (rng.random(n) < 0.7).astype(int)
    df.index = pd.RangeIndex(1000, 1000 + n, name="TransactionID")
    return df


def make_catalog(df: pd.DataFrame) -> pd.DataFrame:
    """Catalog for the synthetic frame (engineered = context group, C/D/V = passthrough)."""
    names = [c for c in df.columns if c not in ("entity_key", "has_device")]

    def group(name: str) -> str:
        if name[0] in "CDV" and name[1:].isdigit():
            return "passthrough"
        return "temporal" if name == "day_index" else "context"

    return pd.DataFrame({"name": names, "group": [group(n) for n in names], "model_input": True})


@pytest.fixture(scope="session")
def features() -> pd.DataFrame:
    return make_features()


@pytest.fixture(scope="session")
def catalog(features: pd.DataFrame) -> pd.DataFrame:
    return make_catalog(features)


@pytest.fixture(scope="session")
def cfg() -> dict:
    return load_anomaly_config()


@pytest.fixture(scope="session")
def weights() -> dict:
    return load_weights()
