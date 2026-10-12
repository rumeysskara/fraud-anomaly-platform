"""Every rule: one record that triggers it and one near miss that does not."""

from __future__ import annotations

import pytest

TRUSTED = {
    "ent_txn_count": 200,
    "ent_age_days": 40.0,
    "amt_zscore_ent": 1.0,
    "device_ent_match": 1,
    "email_ent_known": 1,
}

# rule id -> (changes that trigger it, changes that just miss it)
CASES = {
    "R01": (
        {"TransactionAmt": 10.0, "small_amt_streak_1h": 2},
        {"TransactionAmt": 10.0, "small_amt_streak_1h": 1},
    ),
    "R02": (
        {"TransactionAmt": 500.0, "foreign_addr2": True, "addr2": 96.0, "is_low_volume_window": 1},
        {"TransactionAmt": 500.0, "foreign_addr2": True, "addr2": 96.0, "is_low_volume_window": 0},
    ),
    "R03": (
        {"ent_cnt_1h": 12, "ent_txn_count": 10, "ent_age_days": 10.0},
        {"ent_cnt_1h": 12, "ent_txn_count": 1000, "ent_age_days": 10.0},
    ),
    "R04": (
        {"card_age_days": 0.0, "TransactionAmt": 500.0},
        {"card_age_days": 0.0, "TransactionAmt": 300.0},
    ),
    "R05": (
        {"TransactionAmt": 500.0, "foreign_addr2": True, "addr2": 96.0},
        {"TransactionAmt": 500.0, "foreign_addr2": False},
    ),
    "R06": (
        {"amt_ratio_to_ent_avg": 6.0, "ent_txn_count": 10},
        {"amt_ratio_to_ent_avg": 6.0, "ent_txn_count": 4},
    ),
    "R07": (
        {"is_first_seen": True, "ent_txn_count": 0, "TransactionAmt": 500.0},
        {"is_first_seen": True, "ent_txn_count": 0, "TransactionAmt": 100.0},
    ),
    "R08": (
        {"has_identity": False, "TransactionAmt": 500.0, "ProductCD": "C"},
        {"has_identity": False, "TransactionAmt": 500.0, "ProductCD": "W"},
    ),
    "R09": (
        {"email_mismatch": True, "R_emaildomain": "yahoo.com", "TransactionAmt": 500.0},
        {"email_mismatch": True, "R_emaildomain": "yahoo.com", "TransactionAmt": 100.0},
    ),
    "R10": (TRUSTED, {**TRUSTED, "small_amt_streak_1h": 2}),
    "R11": (
        {"amt_has_3dec": True, "addr2": None, "addr2_missing": True, "TransactionAmt": 500.125},
        {"amt_has_3dec": True, "addr2": 87.0, "TransactionAmt": 500.125},
    ),
    "R12": (
        {"holiday_season": 1, "card_age_days": 0.0, "TransactionAmt": 500.0},
        {"holiday_season": 0, "card_age_days": 0.0, "TransactionAmt": 500.0},
    ),
}


def test_neutral_record_triggers_nothing(engine, neutral):
    result = engine.evaluate(neutral, 0.5)
    assert result.triggered_rules == []
    assert result.final_decision == "allow"
    assert result.decision_source == "default"
    assert result.final_score == pytest.approx(0.5)


def test_every_loaded_rule_has_a_case(repo):
    assert {r.id for r in repo.rules} == set(CASES)


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_rule_triggers(engine, neutral, rule_id):
    hit, _ = CASES[rule_id]
    result = engine.evaluate({**neutral, **hit}, 0.5)
    assert rule_id in result.triggered_rules


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_rule_does_not_trigger(engine, neutral, rule_id):
    _, miss = CASES[rule_id]
    result = engine.evaluate({**neutral, **miss}, 0.5)
    assert rule_id not in result.triggered_rules


def test_message_uses_real_values(engine, neutral):
    result = engine.evaluate({**neutral, **CASES["R01"][0]}, 0.5)
    assert result.reasons[0].startswith("Kart testi şüphesi: 10.00 USD")
    assert "2 önceki küçük işlem" in result.reasons[0]
    assert result.flags == ["card_testing"]


def test_missing_input_is_an_error(engine, neutral):
    record = dict(neutral)
    del record["small_amt_streak_1h"]
    with pytest.raises(KeyError, match="small_amt_streak_1h"):
        engine.evaluate(record, 0.5)


def test_disabled_rule_is_ignored(engine, neutral, repo):
    rules = [r.model_copy(update={"enabled": False}) if r.id == "R01" else r for r in repo.rules]
    result = engine.evaluate({**neutral, **CASES["R01"][0]}, 0.5, rules=rules)
    assert "R01" not in result.triggered_rules


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_r10_never_trusts_an_addr1_missing_entity(engine, neutral, missing):
    """K-55: with addr1 missing the entity key is card1 alone, so R10 must not fire."""
    assert "R10" in engine.evaluate({**neutral, **TRUSTED}, 0.5).triggered_rules
    result = engine.evaluate({**neutral, **TRUSTED, "addr1": missing}, 0.5)
    assert "R10" not in result.triggered_rules
