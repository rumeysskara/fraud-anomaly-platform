"""Synthetic fixtures for the rule engine (no real data; thresholds are given, not learned)."""

from __future__ import annotations

from typing import Any

import pytest

from src.core.config import CONFIG_DIR
from src.rules.cooldown import CooldownStore
from src.rules.engine import RuleEngine
from src.rules.repository import RuleRepository

PARAMS = {
    "amount_small": 25.0,
    "amount_high": 400.0,
    "velocity_1h_extreme": 10.0,
    "score_review_threshold": 0.9,
    "trusted_min_history": 100.0,
}


@pytest.fixture
def repo() -> RuleRepository:
    return RuleRepository(CONFIG_DIR / "rules.yaml")


@pytest.fixture
def engine(repo: RuleRepository) -> RuleEngine:
    return RuleEngine(repo, PARAMS, CooldownStore())


@pytest.fixture
def neutral() -> dict[str, Any]:
    """A record that triggers no rule."""
    return {
        "small_amt_streak_1h": 0,
        "ent_cnt_1h": 0,
        "ent_txn_count": 10,
        "ent_age_days": 10.0,
        "ent_avg_amt": 100.0,
        "amt_ratio_to_ent_avg": 1.0,
        "amt_zscore_ent": 0.0,
        "is_first_seen": False,
        "card_age_days": 50.0,
        "foreign_addr2": False,
        "addr2_missing": False,
        "is_low_volume_window": 0,
        "local_hour_est": 12,
        "is_weekend": 0,
        "has_identity": True,
        "email_mismatch": False,
        "amt_has_3dec": False,
        "holiday_season": 0,
        "device_ent_match": 0,
        "TransactionAmt": 100.0,
        "ProductCD": "W",
        "addr2": 87.0,
        "P_emaildomain": "gmail.com",
        "R_emaildomain": None,
        "email_ent_known": 0,
        "TransactionID": 1,
        "TransactionDT": 86400,
        "card1": 1000,
        "addr1": 300.0,
    }
