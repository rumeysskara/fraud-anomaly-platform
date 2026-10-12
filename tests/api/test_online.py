"""OnlineScorer: idempotency, history updates, read-only analysis (fakes, no artifacts)."""

from __future__ import annotations

from typing import Any

from tests.api.conftest import PAYLOAD, FakeRAG, World


def txn(**changes: Any) -> dict[str, Any]:
    return {**PAYLOAD, **changes}


def test_score_returns_scores_context_and_decision(world: World) -> None:
    outcome, duplicate, _ = world.scorer.score(txn())
    assert not duplicate
    assert outcome.anomaly_score == 0.4
    assert outcome.adjusted_score == 0.4 * 0.9
    assert [c["id"] for c in outcome.context_rules] == ["C1"]
    assert outcome.rule.final_decision == "allow"
    assert set(outcome.layer_scores) == {"column", "multivariate", "entity", "temporal"}


def test_record_has_features_raw_fields_aux_and_email_flag(world: World) -> None:
    world.scorer.score(txn())
    record = world.scoring.records[0]
    assert record["small_amt_streak_1h"] == 0  # feature
    assert record["TransactionAmt"] == 120.0 and record["ProductCD"] == "W"  # raw
    assert record["entity_key"] == "1000.0|300.0"  # aux, numeric keys like the batch path
    assert record["has_device"] == 0
    assert record["email_ent_known"] == 0  # entity not seen yet
    assert record["TransactionID"] == 100


def test_history_is_appended_once_per_transaction_id(world: World) -> None:
    first, _, _ = world.scorer.score(txn())
    again, duplicate, _ = world.scorer.score(txn())
    assert duplicate and again is first
    assert len(world.pipeline.store.updates) == 1
    assert len(world.scoring.detectors["temporal"].store.updates) == 1
    assert world.pipeline.calls == 1  # the repeat did not even build features


def test_email_known_flag_comes_from_the_entity_history(world: World) -> None:
    world.scorer.score(txn(TransactionID=1))
    world.scorer.score(txn(TransactionID=2, TransactionDT=90000))
    assert [r["email_ent_known"] for r in world.scoring.records] == [0, 1]
    world.scorer.score(txn(TransactionID=3, P_emaildomain="other.com"))
    assert world.scoring.records[2]["email_ent_known"] == 0


def test_analyze_is_read_only(world: World) -> None:
    record, outcome = world.scorer.analyze(txn())
    assert outcome.transaction_id == 100 and record["TransactionID"] == 100
    assert world.pipeline.store.updates == []
    assert world.scoring.detectors["temporal"].store.updates == []
    assert world.cooldown.size() == (0, 0)


def test_analyze_after_score_reuses_the_record_before_the_update(world: World) -> None:
    world.scorer.score(txn())
    world.pipeline.features["ent_txn_count"] = 999  # the history moved on
    record, _ = world.scorer.analyze(txn())
    assert record["ent_txn_count"] == 10  # features from the time of /score


def test_out_of_order_transaction_is_flagged(world: World) -> None:
    world.pipeline.features["time_since_last_txn"] = -50.0
    outcome, _, _ = world.scorer.score(txn())
    assert "out_of_order_transaction" in outcome.warnings


def test_cooldown_state_is_written_once_and_request_rules_never_write(world: World) -> None:
    world.pipeline.features.update({"ent_cnt_1h": 15, "ent_txn_count": 10, "ent_age_days": 10.0})
    first, _, _ = world.scorer.score(txn(TransactionID=1))
    assert "R03" in first.rule.triggered_rules
    second, _, _ = world.scorer.score(txn(TransactionID=2, TransactionDT=86400 + 600))
    assert "R03" not in second.rule.triggered_rules  # cooldown: one alert per burst
    assert world.cooldown.size()[1] == 2  # both ids processed, state written once each
    assert world.rag.calls == []


def test_unused_rag_is_not_touched(world: World) -> None:
    world.scorer.score(txn())
    assert isinstance(world.rag, FakeRAG) and world.rag.calls == []
