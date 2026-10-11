"""Batch == single record, params, report helpers, container, no label in src/rules."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.core.config import ROOT_DIR
from src.rules.derive import add_derived
from src.rules.engine import ADJUSTED, ADJUSTED_UNCLIPPED, ANOMALY, FINAL_UNCLIPPED, RuleEngine
from src.rules.explain import render_message
from src.rules.params import external_params, fit_params, write_learned_block
from src.rules.report import decision_distribution, pick_conflict_examples, rule_coverage


def synthetic_frame(neutral: dict, n: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(42)
    df = pd.DataFrame([neutral] * n, index=pd.Index(range(1000, 1000 + n), name="TransactionID"))
    df["TransactionAmt"] = rng.choice([5.0, 100.0, 500.0], n)
    df["small_amt_streak_1h"] = rng.integers(0, 4, n)
    df["card_age_days"] = rng.choice([0.0, 30.0], n)
    df["foreign_addr2"] = rng.random(n) < 0.3
    df["addr2"] = np.where(df["foreign_addr2"], 96.0, 87.0)
    df["is_low_volume_window"] = rng.integers(0, 2, n)
    df["ent_txn_count"] = rng.choice([0, 10, 200], n)
    df["is_first_seen"] = df["ent_txn_count"] == 0
    df["ent_age_days"] = rng.choice([1.0, 40.0], n)
    df["ent_cnt_1h"] = rng.choice([0, 15], n)
    df["amt_ratio_to_ent_avg"] = rng.choice([1.0, 6.0], n)
    df["device_ent_match"] = rng.integers(0, 2, n)
    df["email_ent_known"] = rng.integers(0, 2, n)
    df["has_identity"] = rng.random(n) < 0.5
    df["ProductCD"] = rng.choice(["W", "C"], n)
    adj = rng.uniform(0, 1.3, n)
    scores = pd.DataFrame(
        {ANOMALY: rng.uniform(0, 1, n), ADJUSTED: np.clip(adj, 0, 1), ADJUSTED_UNCLIPPED: adj},
        index=df.index,
    )
    return df, scores


def test_batch_equals_single_record(engine, neutral):
    df, scores = synthetic_frame(neutral)
    batch = engine.evaluate_batch(df, scores)
    assert batch["triggered_rules"].map(len).gt(0).mean() > 0.5
    assert {"block", "review", "allow"} <= set(batch["final_decision"])
    for tid in df.index:
        record = {
            **df.loc[tid].to_dict(),
            ANOMALY: scores.at[tid, ANOMALY],
            ADJUSTED: scores.at[tid, ADJUSTED],
        }
        one = engine.evaluate(record, float(scores.at[tid, ADJUSTED_UNCLIPPED]))
        assert one.triggered_rules == batch.at[tid, "triggered_rules"]
        assert one.final_decision == batch.at[tid, "final_decision"]
        assert one.final_score_unclipped == pytest.approx(batch.at[tid, FINAL_UNCLIPPED])
    assert (batch["final_score"] <= 1.0).all()
    assert batch[FINAL_UNCLIPPED].max() > 1.0  # ranking score is not clipped


def test_report_helpers(engine, neutral):
    df, scores = synthetic_frame(neutral)
    batch = engine.evaluate_batch(df, scores)
    parts = {"fit": df.index[:200], "holdout": df.index[200:]}
    entity = pd.Series(np.where(df.index % 2 == 0, "a", "b"), index=df.index)
    cov = rule_coverage(batch, engine.active_rules(), parts, entity)
    assert len(cov) == len(engine.active_rules()) and (cov["fit_hits"] >= cov["fit_winner"]).all()
    assert (cov["fit_hits_before_cooldown"] >= cov["fit_hits"]).all()
    hit = cov[cov["fit_hits"] > 0]
    assert ((hit["fit_top1_entity_share"] >= 0.5) & (hit["fit_top5_entity_share"] == 1.0)).all()
    dist = decision_distribution(batch, parts)
    assert dist.groupby("part")["rows"].sum().tolist() == [200, 100]
    picked = pick_conflict_examples(batch, batch.index, {"R10"}, n=2)
    assert all(len(batch.at[t, "suppressed_rules"]) > 0 for t in picked)


def test_derived_columns():
    df = pd.DataFrame(
        {
            "ent_txn_count": [0, 20],
            "ent_age_days": [0.0, 10.0],
            "ent_cnt_1h": [0, 8],
            "device_ent_match": [0, 2],
            "email_ent_known": [1, 0],
        }
    )
    out = add_derived(df, 1.0)
    assert out["ent_daily_avg"].tolist() == [0.0, 2.0]
    assert np.isnan(out["burst_ratio_1h"].iloc[0]) and out["burst_ratio_1h"].iloc[1] == 4.0
    assert out["known_device"].tolist() == [0, 1] and out["known_email"].tolist() == [1, 0]


def test_fit_params_use_quantiles(repo):
    df = pd.DataFrame(
        {
            "TransactionAmt": np.arange(1, 101, dtype=float),
            "ent_cnt_1h": np.arange(100),
            ADJUSTED_UNCLIPPED: np.linspace(0, 1, 100),
        }
    )
    learned = fit_params(df, repo.settings)
    assert learned["amount_small"] == pytest.approx(np.quantile(df["TransactionAmt"], 0.10))
    assert learned["amount_high"] == pytest.approx(np.quantile(df["TransactionAmt"], 0.95))
    assert learned["n_fit"] == 100


def test_learned_block_round_trip(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text("a: 1  # keep me\n")
    write_learned_block(path, {"x": 1.5})
    write_learned_block(path, {"x": 2.5})
    text = path.read_text()
    assert "# keep me" in text and text.count("learned:") == 1
    assert yaml.safe_load(text)["learned"] == {"x": 2.5}


def test_external_params_read_artifact(tmp_path: Path, repo):
    (tmp_path / "context_params.json").write_text(
        json.dumps({"values": {"trusted_min_history": 42.0}})
    )
    settings = repo.settings
    settings.external_params = {
        "trusted_min_history": {
            "dir": str(tmp_path),
            "file": "context_params.json",
            "key": "trusted_min_history",
        }
    }
    assert external_params(settings) == {"trusted_min_history": 42.0}


def test_render_message_missing_value():
    assert render_message("{a:.2f} / {b}", {"a": 1.234, "b": None}) == "1.23 / yok"


def test_container_providers(monkeypatch):
    from dependency_injector import providers

    from src.container import Container

    container = Container()
    repo = container.rule_repository()
    assert len(repo.rules) >= 10
    fake = RuleEngine(repo, {})
    container.rule_engine.override(providers.Object(fake))
    assert container.rule_engine() is fake


def test_label_never_used_in_rules_code_or_config():
    paths = list((ROOT_DIR / "src" / "rules").glob("*.py"))
    paths += [ROOT_DIR / "configs" / "rules.yaml", ROOT_DIR / "configs" / "rules_extra.json"]
    for path in paths:
        assert "isFraud" not in path.read_text(), path
