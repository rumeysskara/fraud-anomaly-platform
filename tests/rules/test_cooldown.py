"""R03 cooldown: once per entity per window, past-only, batch == online, idempotent store."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.rules.cooldown import CooldownStore, apply_cooldown
from src.rules.engine import ADJUSTED, ADJUSTED_UNCLIPPED, ANOMALY, RuleEngine

R03_DICT = {
    "id": "R03",
    "name": "velocity_burst_request",
    "priority": 2,
    "severity": "high",
    "condition": {"feature": "ent_cnt_1h", "op": ">=", "value": 10},
    "action": {"risk_boost": 0.15, "decision": "review", "flag": "v"},
    "message": "burst",
    "cooldown": {"window_seconds": 3600},
}


def test_apply_cooldown_keeps_first_hit_per_window():
    hit = np.array([True, True, True, True, True])
    times = np.array([0, 100, 3599, 3600, 50], dtype=float)
    keys = np.array(["a", "a", "a", "a", "b"])
    kept = apply_cooldown(hit, times, keys, 3600, {})
    assert kept.tolist() == [True, False, False, True, True]


def test_apply_cooldown_uses_only_earlier_rows():
    # unsorted input: the hit at t=0 is visited first even though it is the last row
    kept = apply_cooldown(
        np.array([True, True]), np.array([10.0, 0.0]), np.array(["a", "a"]), 60, {}
    )
    assert kept.tolist() == [False, True]


def test_equal_times_are_ordered_by_transaction_id():
    hit = np.array([True, True])
    kept = apply_cooldown(
        hit, np.array([5.0, 5.0]), np.array(["a", "a"]), 60, {}, ids=np.array([9, 3])
    )
    assert kept.tolist() == [False, True]  # id 3 is earlier


def test_state_carries_over():
    state: dict[str, float] = {"a": 0.0}
    kept = apply_cooldown(np.array([True]), np.array([30.0]), np.array(["a"]), 60, state)
    assert kept.tolist() == [False] and state == {"a": 0.0}


def burst_frame(neutral: dict, n: int = 6) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for i in range(n):
        rows.append(
            {
                **neutral,
                "TransactionID": 100 + i,
                "ent_cnt_1h": 12,
                "ent_txn_count": 10,
                "ent_age_days": 10.0,
                "TransactionDT": 1000 + i * 1500,  # 25 minutes apart
                "card1": 1000 if i % 2 == 0 else 2000,
            }
        )
    df = pd.DataFrame(rows).set_index("TransactionID", drop=False).rename_axis("TransactionID")
    scores = pd.DataFrame({ANOMALY: 0.5, ADJUSTED: 0.5, ADJUSTED_UNCLIPPED: 0.5}, index=df.index)
    return df, scores


def test_batch_cooldown_and_online_replay(engine, neutral):
    df, scores = burst_frame(neutral)
    batch = engine.evaluate_batch(df, scores)
    # rows alternate entities: 1000 at t=1000, 4000, 7000 -> fires at 1000 and 7000 (4000 is
    # 3000 s after the last kept fire); 2000 at t=2500, 5500, 8500 -> fires at 2500 and 8500
    assert batch["hit_R03"].tolist() == [1, 1, 0, 0, 1, 1]
    assert batch.loc[102, "cooldown_rules"] == ["R03"]
    assert engine.cooldown_store.size() == (0, 0)  # batch never touches the online store
    for tid in df.index:  # online path, same order, shared store
        one = engine.evaluate(df.loc[tid].to_dict(), 0.5)
        assert ("R03" in one.triggered_rules) == bool(batch.at[tid, "hit_R03"])
        if not batch.at[tid, "hit_R03"]:
            assert one.suppressed_rules[-1]["id"] == "R03"
            assert one.suppressed_rules[-1]["reason"].startswith("cooldown")


def test_same_transaction_twice_gives_same_result(engine, neutral):
    df, _ = burst_frame(neutral, 1)
    record = df.iloc[0].to_dict()
    first = engine.evaluate(record, 0.5)
    second = engine.evaluate(record, 0.5)
    assert "R03" in first.triggered_rules and first.explain_dict() == second.explain_dict()
    assert engine.cooldown_store.size() == (1, 1)  # written once


def test_next_transaction_of_entity_is_cooled(engine, neutral):
    df, _ = burst_frame(neutral, 3)
    engine.evaluate(df.iloc[0].to_dict(), 0.5)
    third = engine.evaluate(df.iloc[2].to_dict(), 0.5)  # same entity, 3000 s later
    assert "R03" not in third.triggered_rules


def test_read_only_evaluation_does_not_update_state(engine, neutral):
    df, _ = burst_frame(neutral, 3)
    assert "R03" in engine.evaluate(df.iloc[0].to_dict(), 0.5, update_state=False).triggered_rules
    assert engine.cooldown_store.size() == (0, 0)
    assert "R03" in engine.evaluate(df.iloc[2].to_dict(), 0.5).triggered_rules


def test_request_time_rule_set_reads_but_never_writes(engine, neutral):
    df, _ = burst_frame(neutral, 3)
    # request-time set alone: fires, but nothing is stored
    assert "R03" in engine.evaluate(df.iloc[0].to_dict(), 0.5, rules=[R03_DICT]).triggered_rules
    assert engine.cooldown_store.size() == (0, 0)
    # loaded set records the fire; the request-time set then READS it
    engine.evaluate(df.iloc[0].to_dict(), 0.5)
    before = engine.cooldown_store.size()
    later = engine.evaluate(df.iloc[2].to_dict(), 0.5, rules=[R03_DICT])
    assert "R03" not in later.triggered_rules
    assert engine.cooldown_store.size() == before


def test_store_drops_entries_older_than_window():
    store = CooldownStore()
    store.record(1, 0.0, [("R03", "a")], 3600)
    store.record(2, 1000.0, [], 3600)
    assert store.size() == (1, 2)
    store.record(3, 5000.0, [("R03", "b")], 3600)  # newest 5000 -> limit 1400
    assert store.size() == (1, 1) and not store.is_processed(1) and store.is_processed(3)
    assert store.last_fire_before("R03", "a", 5000.0, 4) is None


def test_store_is_injected_not_created(repo):
    store = CooldownStore()
    assert RuleEngine(repo, {}, store).cooldown_store is store
