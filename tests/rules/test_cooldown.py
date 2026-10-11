"""R03 cooldown: once per entity per window, past-only, batch == online replay."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.rules.cooldown import CooldownStore, apply_cooldown
from src.rules.engine import ADJUSTED, ADJUSTED_UNCLIPPED, ANOMALY


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
                "ent_cnt_1h": 12,
                "ent_txn_count": 10,
                "ent_age_days": 10.0,
                "TransactionDT": 1000 + i * 1500,  # 25 minutes apart
                "card1": 1000 if i % 2 == 0 else 2000,
            }
        )
    df = pd.DataFrame(rows, index=pd.Index(range(n), name="TransactionID"))
    scores = pd.DataFrame({ANOMALY: 0.5, ADJUSTED: 0.5, ADJUSTED_UNCLIPPED: 0.5}, index=df.index)
    return df, scores


def test_batch_cooldown_and_online_replay(engine, neutral):
    df, scores = burst_frame(neutral)
    batch = engine.evaluate_batch(df, scores)
    # rows alternate entities: 1000 at t=1000, 4000, 7000 -> fires at 1000 and 7000 (4000 is
    # 3000 s after the last kept fire); 2000 at t=2500, 5500, 8500 -> fires at 2500 and 8500
    assert batch["hit_R03"].tolist() == [1, 1, 0, 0, 1, 1]
    assert batch.loc[2, "cooldown_rules"] == ["R03"]
    engine.cooldown_store = CooldownStore()
    for tid in df.index:  # online path, same order, shared state
        one = engine.evaluate(df.loc[tid].to_dict(), 0.5)
        assert ("R03" in one.triggered_rules) == bool(batch.at[tid, "hit_R03"])
        if not batch.at[tid, "hit_R03"]:
            assert one.suppressed_rules[-1]["id"] == "R03"
            assert one.suppressed_rules[-1]["reason"].startswith("cooldown")


def test_read_only_evaluation_does_not_update_state(engine, neutral):
    df, _ = burst_frame(neutral, 1)
    record = df.iloc[0].to_dict()
    engine.cooldown_store = CooldownStore()
    assert "R03" in engine.evaluate(record, 0.5, update_state=False).triggered_rules
    assert "R03" in engine.evaluate(record, 0.5).triggered_rules
    assert "R03" not in engine.evaluate(record, 0.5).triggered_rules
