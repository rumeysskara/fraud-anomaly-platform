"""Each context rule: triggered and not triggered, plus guard, bounds and clip."""

from __future__ import annotations

import math

import pytest

from src.context.config import ContextConfig


def factor_of(cfg: ContextConfig, rule_id: str) -> float:
    return next(r.factor for r in cfg.rules if r.id == rule_id)


# C4 (revised): history >= learned q90 (20 in the fixture), age >= 30 d, device AND e-mail known
TRUSTED = {"ent_txn_count": 25, "ent_age_days": 100.0, "device_ent_match": 2, "email_ent_known": 1}

# rule id -> (changes that trigger it, changes that keep it silent)
CASES = {
    "C1": (
        {"local_hour_est": 10, "ent_txn_count": 1, "ent_age_days": 0.5},
        {"local_hour_est": 10, "ent_txn_count": 0},
    ),
    "C2": (
        {"is_low_volume_window": 1, "TransactionAmt": 150.0},
        {"is_low_volume_window": 1, "TransactionAmt": 99.0},
    ),
    "C3": (
        {"is_weekend": 1, "ent_txn_count": 5, "ent_age_days": 30.0},
        {"is_weekend": 1, "ent_txn_count": 4, "ent_age_days": 30.0},
    ),
    "C4": (
        {**TRUSTED, "amt_zscore_ent": -1.5},
        {**TRUSTED, "amt_zscore_ent": 2.5},
    ),
    "C6a": ({"addr2": 60.0}, {"addr2": 87.0}),
    "C6b": ({"addr2": float("nan"), "amt_has_3dec": 1}, {"addr2": float("nan"), "amt_has_3dec": 0}),
    "C8": (
        {"card_age_days": 0.0, "TransactionAmt": 300.0},
        {"card_age_days": 1.0, "TransactionAmt": 300.0},
    ),
    "C9a": ({"ProductCD": "C"}, {"ProductCD": "R"}),
    "C9b": ({"ProductCD": "W"}, {"ProductCD": "S"}),
}


@pytest.mark.parametrize("rule_id", list(CASES))
def test_multiplicative_rule_triggers(engine, cfg, neutral, rule_id):
    on, off = CASES[rule_id]
    res = engine.adjust_one({**neutral, **on}, 0.4)
    assert res.applied_rules == [rule_id]
    assert res.adjusted_score == pytest.approx(0.4 * factor_of(cfg, rule_id))
    silent = engine.adjust_one({**neutral, **off}, 0.4)
    assert rule_id not in silent.applied_rules


def test_neutral_record_is_unchanged(engine, neutral):
    res = engine.adjust_one(neutral, 0.4)
    assert res.applied_rules == []
    assert res.adjusted_score == pytest.approx(0.4)


@pytest.mark.parametrize(
    "change",
    [
        {"device_ent_match": 0},  # e-mail alone is not enough
        {"email_ent_known": 0},  # device alone is not enough
        {"ent_txn_count": 19},  # below the learned history threshold
        {"ent_age_days": 29.0},  # younger than 30 days
    ],
)
def test_c4_needs_every_clause(engine, neutral, change):
    assert engine.adjust_one({**neutral, **TRUSTED}, 0.4).applied_rules == ["C4"]
    assert "C4" not in engine.adjust_one({**neutral, **TRUSTED, **change}, 0.4).applied_rules


@pytest.mark.parametrize(
    "change, kept",
    [
        ({"addr2": float("nan"), "amt_has_3dec": 1, "ProductCD": "C"}, "C6b"),  # tie 1.10: first
        ({"addr2": 60.0, "ProductCD": "C"}, "C6a"),  # 1.20 beats 1.10
        ({"addr2": 60.0, "ProductCD": "W"}, "C6a"),  # 1.20 beats 0.95
    ],
)
def test_c6_c9_exclusive_group_keeps_largest(engine, cfg, neutral, change, kept):
    res = engine.adjust_one({**neutral, **change}, 0.4)
    assert res.applied_rules == [kept]
    assert res.adjusted_score == pytest.approx(0.4 * factor_of(cfg, kept))


FREQUENT = {"ent_txn_count": 10, "ent_age_days": 5.0}  # daily average 2


def test_c5_halves_temporal_weight(engine, neutral):
    rec = {
        **neutral,
        **FREQUENT,
        "ent_cnt_24h": 4,  # 2x own daily average -> normal rhythm
        "temporal_score": 0.95,
        "multivariate_score": 0.3,
        "entity_score": 0.3,
        "column_score": 0.3,
    }
    res = engine.adjust_one(rec, 0.6)
    assert "C5" in res.applied_rules
    assert res.adjusted_score < 0.6
    c5 = next(e for e in res.explanations if e.details.get("id") == "C5")
    assert 0.5 <= c5.details["factor"] < 1.0


def test_c5_silent_on_real_burst_and_on_low_temporal(engine, neutral):
    burst = {**neutral, **FREQUENT, "ent_cnt_24h": 10, "temporal_score": 0.95}  # 5x average
    assert "C5" not in engine.adjust_one(burst, 0.6).applied_rules
    # halving a LOW temporal score would raise the aggregate; only_if_lowers keeps it silent
    low = {**neutral, **FREQUENT, "ent_cnt_24h": 2, "temporal_score": 0.05}
    assert "C5" not in engine.adjust_one(low, 0.6).applied_rules


def test_c7_needs_temporal_dominant(engine, cfg, neutral):
    rec = {**neutral, "holiday_season": 1, "temporal_score": 0.99, "multivariate_score": 0.2}
    res = engine.adjust_one(rec, 0.5)
    assert res.applied_rules == ["C7"]
    assert res.adjusted_score == pytest.approx(0.5 * factor_of(cfg, "C7"))
    other = {**neutral, "holiday_season": 1, "temporal_score": 0.2, "multivariate_score": 0.99}
    assert "C7" not in engine.adjust_one(other, 0.5).applied_rules


def test_guard_keeps_card_testing_at_raw_score(engine, neutral):
    trusted = {
        **neutral,
        **TRUSTED,
        "local_hour_est": 10,
        "ProductCD": "W",
    }
    discounted = engine.adjust_one(trusted, 0.6)
    assert discounted.adjusted_score < 0.6
    guarded = engine.adjust_one({**trusted, "small_amt_streak_1h": 2}, 0.6)
    assert guarded.adjusted_score == pytest.approx(0.6)
    assert "G1" in guarded.applied_rules


def test_guard_does_not_block_increases(engine, neutral):
    rec = {**neutral, "small_amt_streak_1h": 3, "addr2": 60.0}
    assert engine.adjust_one(rec, 0.5).adjusted_score == pytest.approx(0.5 * 1.2)


def test_total_factor_is_bounded_and_score_clipped(engine, cfg, neutral):
    rec = {
        **neutral,
        "is_low_volume_window": 1,
        "TransactionAmt": 500.0,
        "card_age_days": 0.0,
        "addr2": 60.0,
        "ProductCD": "C",
    }
    # C9a is dropped by the C6/C9 exclusive group (C6a is larger)
    unbounded = math.prod(factor_of(cfg, i) for i in ("C2", "C8", "C6a"))
    assert unbounded > cfg.max_total
    res = engine.adjust_one(rec, 0.5)
    assert res.adjusted_score == pytest.approx(0.5 * cfg.max_total)
    assert "BOUNDS" in res.applied_rules
    high = engine.adjust_one(rec, 0.9)
    assert high.adjusted_score == 1.0  # output is clipped
    total = next(e for e in high.explanations if "total" in e.details)
    assert total.details["adjusted_score_unclipped"] == pytest.approx(0.9 * cfg.max_total)


def test_lower_bound(engine, cfg, neutral):
    # C1 x C4 x C9b x C5 multiply to about 0.35; the bounds lift the total to min_total
    rec = {
        **neutral,
        **TRUSTED,
        "ent_txn_count": 40,
        "ent_age_days": 30.0,  # daily average 1.33 -> C5 frequent entity
        "ent_cnt_24h": 3,
        "local_hour_est": 10,
        "ProductCD": "W",
        "temporal_score": 1.0,
        "multivariate_score": 0.0,
        "entity_score": 0.0,
        "column_score": 0.0,
    }
    res = engine.adjust_one(rec, 0.3)
    assert res.adjusted_score == pytest.approx(0.3 * cfg.min_total)
    assert "BOUNDS" in res.applied_rules
