"""Synthetic fixtures for the context engine (no real data)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from src.context.config import ContextConfig, load_context_config
from src.context.engine import ContextAdjustEngine
from src.context.params import ContextParams
from src.detection.normalization import QuantileNormalizer

WEIGHTS = {"multivariate": 0.35, "entity": 0.25, "column": 0.20, "temporal": 0.20}


@pytest.fixture
def cfg() -> ContextConfig:
    return load_context_config()


@pytest.fixture
def params() -> ContextParams:
    return ContextParams(
        values={"amount_high": 100.0, "dominant_addr2": 87.0, "trusted_min_history": 20.0},
        n_fit=1000,
    )


@pytest.fixture
def normalizer() -> QuantileNormalizer:
    rng = np.random.default_rng(42)
    return QuantileNormalizer(101).fit(rng.uniform(0, 1, 5000))


@pytest.fixture
def engine(cfg, params, normalizer) -> ContextAdjustEngine:
    return ContextAdjustEngine(cfg, params, WEIGHTS, normalizer)


@pytest.fixture
def neutral() -> dict[str, Any]:
    """A record that triggers no rule and no guard."""
    return {
        "local_hour_est": 3,
        "is_weekend": 0,
        "is_low_volume_window": 0,
        "ent_txn_count": 0,
        "ent_age_days": 0.0,
        "ent_cnt_24h": 0,
        "amt_zscore_ent": 0.0,
        "device_ent_match": 0,
        "amt_has_3dec": 0,
        "holiday_season": 0,
        "card_age_days": 100.0,
        "small_amt_streak_1h": 0,
        "TransactionAmt": 50.0,
        "ProductCD": "H",
        "addr2": 87.0,
        "email_ent_known": 0,
        "multivariate_score": 0.5,
        "entity_score": 0.5,
        "column_score": 0.5,
        "temporal_score": 0.5,
    }
