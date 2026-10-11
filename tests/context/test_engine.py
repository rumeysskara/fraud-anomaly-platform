"""Batch = online (K-01), config validation, params, inputs, ablation helpers, container."""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import pytest

from src.context.conditions import eval_condition
from src.context.config import parse_context_config
from src.context.engine import ADJUSTED_SCORE, APPLIED, ContextAdjustEngine
from src.context.inputs import email_known_batch
from src.context.params import ContextParams
from src.context.report import ablation_variants, alarm_mask, run_ablation
from src.core.config import load_yaml
from tests.context.conftest import WEIGHTS


def _random_frame(neutral: dict, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for _ in range(n):
        rec = dict(neutral)
        rec.update(
            local_hour_est=int(rng.integers(0, 24)),
            is_weekend=int(rng.integers(0, 2)),
            is_low_volume_window=int(rng.integers(0, 2)),
            ent_txn_count=int(rng.integers(0, 40)),
            ent_age_days=float(rng.uniform(0, 30)),
            ent_cnt_24h=int(rng.integers(0, 20)),
            amt_zscore_ent=float(rng.normal(0, 2)),
            device_ent_match=int(rng.integers(0, 3)),
            email_ent_known=int(rng.integers(0, 2)),
            amt_has_3dec=int(rng.integers(0, 2)),
            holiday_season=int(rng.integers(0, 2)),
            card_age_days=float(rng.choice([0.0, 5.0])),
            small_amt_streak_1h=int(rng.integers(0, 3)),
            TransactionAmt=float(rng.uniform(1, 400)),
            ProductCD=str(rng.choice(list("WCRHS"))),
            addr2=float(rng.choice([87.0, 60.0, np.nan])),
            multivariate_score=float(rng.uniform()),
            entity_score=float(rng.uniform()),
            column_score=float(rng.uniform()),
            temporal_score=float(rng.uniform()),
        )
        rows.append(rec)
    return pd.DataFrame(rows, index=pd.RangeIndex(1000, 1000 + n, name="TransactionID"))


def test_batch_equals_one(engine, neutral):
    df = _random_frame(neutral)
    raw = pd.Series(np.random.default_rng(1).uniform(size=len(df)), index=df.index)
    batch = engine.adjust_batch(df, raw)
    for tid, row in df.iterrows():
        one = engine.adjust_one(row.to_dict(), float(raw[tid]))
        assert one.adjusted_score == pytest.approx(batch.at[tid, ADJUSTED_SCORE])
        assert one.applied_rules == [e["id"] for e in batch.at[tid, APPLIED]]
    # every rule fires somewhere in the random frame
    fired = {e["id"] for lst in batch[APPLIED] for e in lst}
    assert {r.id for r in engine.cfg.rules} <= fired


def test_batch_output_schema(engine, neutral):
    df = _random_frame(neutral, 20)
    out = engine.adjust_batch(df, pd.Series(0.5, index=df.index))
    for col in ("raw_score", ADJUSTED_SCORE, "adjustment_total", "guard_active", APPLIED):
        assert col in out.columns
    assert out[ADJUSTED_SCORE].between(0, 1).all()
    assert out["adjustment_total"].between(engine.cfg.min_total, engine.cfg.max_total).all()
    entry = next(lst for lst in out[APPLIED] if lst)[0]
    assert set(entry) == {"id", "name", "factor", "reason"} and entry["reason"]


def test_missing_input_column_raises(engine, neutral):
    rec = dict(neutral)
    rec.pop("addr2")
    with pytest.raises(KeyError):
        engine.adjust_one(rec, 0.5)


def test_config_validation(params, normalizer):
    raw = load_yaml("context.yaml")
    bad = dict(raw, rules=[*raw["rules"], dict(raw["rules"][0])])
    with pytest.raises(ValueError):
        parse_context_config(bad)
    unknown = dict(raw)
    unknown["rules"] = [
        dict(raw["rules"][0], condition={"all": [{"feature": "nope", "op": "==", "value": 1}]})
    ]
    with pytest.raises(ValueError):
        ContextAdjustEngine(parse_context_config(unknown), params, WEIGHTS, normalizer)


def test_every_rule_has_rationale_and_at_least_six(cfg):
    assert len(cfg.groups()) >= 6
    assert all(r.rationale and r.condition["all"] for r in cfg.rules)


def test_nan_never_satisfies_comparison(params):
    df = pd.DataFrame({"addr2": [np.nan, 60.0, 87.0]})
    mask = eval_condition(df, {"all": [{"feature": "addr2", "op": "!=", "value": 87.0}]}, params)
    assert mask.tolist() == [False, True, False]


def test_params_fit_and_roundtrip(cfg, tmp_path):
    fit = pd.DataFrame(
        {"TransactionAmt": np.arange(1, 101, dtype=float), "addr2": [87.0] * 60 + [60.0] * 40}
    )
    p = ContextParams.fit(fit, cfg)
    assert p.get("amount_high") == pytest.approx(np.quantile(np.arange(1, 101), 0.9))
    assert p.get("dominant_addr2") == 87.0
    p.save(tmp_path)
    assert ContextParams.load(tmp_path).values == p.values
    with pytest.raises(KeyError):
        p.get("missing")


def test_email_known_uses_only_earlier_rows():
    raw = pd.DataFrame(
        {
            "TransactionDT": [30, 10, 20, 40, 50],
            "card1": [1, 1, 1, 1, 2],
            "addr1": [5.0, 5.0, 5.0, 5.0, 5.0],
            "P_emaildomain": ["a.com", "a.com", None, None, "a.com"],
        },
        index=[11, 12, 13, 14, 15],
    )
    known = email_known_batch(raw, ["card1", "addr1"])
    # row 12 (dt 10) is the first a.com of entity 1; row 11 (dt 30) has seen it; NaN never known;
    # entity 2 never saw a.com before
    assert known.to_dict() == {11: 1, 12: 0, 13: 0, 14: 0, 15: 0}


def test_alarm_mask_tie_break():
    score = pd.Series([1.0, 1.0, 1.0, 0.2], index=[1, 2, 3, 4])
    tb = pd.Series([0.1, 0.9, 0.5, 0.0], index=[1, 2, 3, 4])
    assert alarm_mask(score, 0.5, tb).tolist() == [False, True, True, False]


def test_ablation_variants_and_run(engine, neutral):
    variants = ablation_variants(engine.cfg)
    n_groups = len(engine.cfg.groups())
    assert len(variants) == 1 + 2 * n_groups + 3
    df = _random_frame(neutral, 50)
    raw = pd.Series(0.5, index=df.index)
    table = run_ablation(engine, df, raw, lambda s: {"mean": float(s.mean())})
    assert len(table) == len(variants) + 1
    assert table.loc[0, "mean"] == pytest.approx(0.5)


def test_context_code_never_reads_label():
    src = pathlib.Path(__file__).resolve().parents[2] / "src" / "context"
    for path in src.glob("*.py"):
        assert "isFraud" not in path.read_text(), path


def test_container_has_context_provider():
    from src.container import Container

    assert hasattr(Container, "context_adjuster")
