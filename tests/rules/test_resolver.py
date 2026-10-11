"""Conflict resolution: priority, severity, decision order, allow, boost cap."""

from __future__ import annotations

import pytest

from src.rules.resolver import resolve
from src.rules.schema import Rule


def rule(rid: str, priority: int, severity: str, decision: str, boost: float = 0.1) -> Rule:
    return Rule.model_validate(
        {
            "id": rid,
            "name": rid.lower(),
            "priority": priority,
            "severity": severity,
            "condition": {"feature": "x", "op": ">", "value": 0},
            "action": {
                "risk_boost": 0.0 if decision == "allow" else boost,
                "decision": decision,
                "flag": rid,
            },
            "message": rid,
        }
    )


def test_no_rule_no_decision():
    res = resolve([], -0.1, 0.4)
    assert res.decision is None and res.boost == 0.0


def test_priority_wins():
    res = resolve([rule("B", 2, "critical", "review"), rule("A", 1, "low", "block")], -0.1, 0.4)
    assert res.winner == "A" and res.decision == "block"
    assert res.suppressed[0][0] == "B" and "daha yüksek öncelik" in res.suppressed[0][1]


def test_severity_breaks_priority_tie():
    res = resolve([rule("A", 2, "medium", "block"), rule("B", 2, "high", "review")], -0.1, 0.4)
    assert res.winner == "B" and res.decision == "review"
    assert "daha yüksek önem" in res.suppressed[0][1]


def test_decision_order_breaks_full_tie():
    res = resolve([rule("A", 2, "high", "review"), rule("B", 2, "high", "block")], -0.1, 0.4)
    assert res.decision == "block"
    assert "block > review > allow" in res.suppressed[0][1]


def test_allow_suppressed_by_higher_or_equal_priority_risk():
    res = resolve([rule("T", 5, "low", "allow"), rule("R", 5, "low", "review")], -0.1, 0.4)
    assert res.decision == "review"
    assert res.suppressed == (("T", res.suppressed[0][1]),)
    assert "allow kuralı" in res.suppressed[0][1]
    # allow with higher severity at the same priority still loses (rule 4)
    res = resolve([rule("T", 3, "critical", "allow"), rule("R", 3, "low", "review")], -0.1, 0.4)
    assert res.decision == "review"


def test_allow_wins_when_risk_rules_have_lower_priority():
    res = resolve([rule("T", 1, "low", "allow"), rule("R", 4, "high", "review")], -0.1, 0.4)
    assert res.decision == "allow" and res.applied == ("T",)
    assert res.boost == 0.0  # the suppressed review boost is not applied


def test_same_decision_rules_are_all_applied_and_boost_is_capped():
    rules = [rule("A", 2, "high", "review", 0.3), rule("B", 3, "medium", "review", 0.3)]
    res = resolve(rules, -0.1, 0.4)
    assert res.applied == ("A", "B") and res.suppressed == ()
    assert res.boost_raw == pytest.approx(0.6) and res.boost == pytest.approx(0.4)


def test_engine_conflict_example(engine, neutral):
    """Real rule set: R02 (p1 block) beats R04 and R05 (p2 review); R02 + R05 would double count."""
    record = {
        **neutral,
        "TransactionAmt": 500.0,
        "foreign_addr2": True,
        "addr2": 96.0,
        "is_low_volume_window": 1,
        "card_age_days": 0.0,
    }
    result = engine.evaluate(record, 0.6)
    assert result.triggered_rules == ["R02", "R04", "R05"]
    assert result.final_decision == "block" and result.applied_rules == ["R02"]
    assert {s["id"] for s in result.suppressed_rules} == {"R04", "R05"}
    assert result.final_score_unclipped == pytest.approx(0.9)


def test_engine_allow_suppressed_by_review(engine, neutral):
    record = {
        **neutral,
        "ent_txn_count": 200,
        "ent_age_days": 40.0,
        "amt_zscore_ent": 1.0,
        "device_ent_match": 1,
        "email_ent_known": 1,
        "card_age_days": 0.0,
        "TransactionAmt": 500.0,
    }
    result = engine.evaluate(record, 0.5)
    assert set(result.triggered_rules) == {"R04", "R10"}
    assert result.final_decision == "review"
    assert result.suppressed_rules[0]["id"] == "R10"


def test_score_fallback(engine, neutral):
    high = engine.evaluate(neutral, 0.95)
    assert high.final_decision == "review" and high.decision_source == "score"
    assert high.final_score == 0.95
    over = engine.evaluate(neutral, 1.3)
    assert over.final_score == 1.0 and over.final_score_unclipped == pytest.approx(1.3)


def trusted_record(neutral: dict) -> dict:
    return {
        **neutral,
        "ent_txn_count": 200,
        "ent_age_days": 40.0,
        "amt_zscore_ent": 1.0,
        "device_ent_match": 1,
        "email_ent_known": 1,
    }


def test_allow_cannot_override_score_review(engine, neutral):
    """Rule 4: a score-threshold review stays review even when R10 (allow) fired."""
    result = engine.evaluate(trusted_record(neutral), 0.95)
    assert result.final_decision == "review" and result.decision_source == "score"
    assert result.applied_rules == []
    assert result.suppressed_rules[0]["id"] == "R10"
    assert "skor eşiğinden" in result.suppressed_rules[0]["reason"]


def test_allow_below_score_threshold_stays_allow(engine, neutral):
    result = engine.evaluate(trusted_record(neutral), 0.5)
    assert result.final_decision == "allow" and result.decision_source == "R10"


def test_allow_never_overrides_block():
    """A block rule beats allow even with a lower priority."""
    res = resolve([rule("T", 1, "low", "allow"), rule("B", 4, "low", "block")], -0.1, 0.4)
    assert res.decision == "block" and res.winner == "B"
    assert "block kararını hiçbir zaman" in res.suppressed[0][1]


def test_allow_overrides_lower_priority_rule_review():
    """Allow does override a REVIEW from a rule with a lower priority (current behaviour)."""
    res = resolve([rule("T", 1, "low", "allow"), rule("R", 3, "high", "review")], -0.1, 0.4)
    assert res.decision == "allow"
    assert res.suppressed[0][0] == "R" and "daha yüksek öncelik" in res.suppressed[0][1]


def test_engine_allow_vs_card_testing_block(engine, neutral):
    record = {**trusted_record(neutral), "TransactionAmt": 10.0, "small_amt_streak_1h": 3}
    result = engine.evaluate(record, 0.3)
    # R10 itself excludes card testing; R01 decides block either way
    assert result.final_decision == "block" and "R10" not in result.applied_rules
