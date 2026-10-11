"""Entity comparison, figures and full report on synthetic data."""

import numpy as np
import pandas as pd

from src.core.config import load_settings
from src.profiling import entity
from src.profiling.config import profiling_config
from src.profiling.report import run_profile


def test_entity_codes_marks_undefined():
    df = pd.DataFrame({"a": [1.0, 1.0, 2.0, np.nan], "b": [5, 5, 5, 5]})
    key = entity.entity_codes(df, ["a", "b"])
    assert key[0] == key[1] != key[2]
    assert key[3] == -1
    assert list(entity.entity_sizes(key)) == [2, 1]


def test_na_as_level_keeps_rows_defined():
    df = pd.DataFrame({"a": [1.0, 1.0, np.nan, np.nan], "b": [5, 5, 5, 6]})
    plain = entity.entity_codes(df, ["a", "b"])
    leveled = entity.entity_codes(df, ["a", "b"], ["a"])
    assert (plain[2:] == -1).all()
    assert (leveled >= 0).all() and len(set(leveled)) == 3


def _cfg(candidates: dict) -> dict:
    return {**profiling_config("entity"), "candidates": candidates}


def test_compare_candidates_known_counts():
    df = pd.DataFrame(
        {
            "k": [1, 1, 1, 2, 3, 1, 2, 4, 5, 5],
            "TransactionAmt": [10.0] * 10,
            "TransactionDT": np.arange(10) * 100,
        }
    )
    res, keys = entity.compare_candidates(df, "TransactionDT", 0.5, _cfg({"K": {"columns": ["k"]}}))
    full = res[res["scope"] == "full"].iloc[0]
    assert full["n_entities"] == 5
    assert full["single_txn_entity_ratio"] == 0.4  # entities 3 and 4
    assert full["txn_max"] == 4
    assert full["undefined_ratio"] == 0
    fit = res[res["scope"] == "fit"].iloc[0]
    assert fit["n_rows"] == 5 and fit["n_entities"] == 3
    # holdout rows {1,2,4,5,5}: entities 1 and 2 were seen in the fit set
    assert full["holdout_seen_ratio"] == 0.4
    assert set(keys) == {"K"}


def test_first_use_day():
    df = pd.DataFrame(
        {"TransactionDT": [86400 * 10 + 5, 86400 * 12, 86400 * 12], "D1": [3, 5, np.nan]}
    )
    d1n = entity.first_use_day(df, "TransactionDT", "D1", 86400)
    assert d1n.iloc[0] == 7 and d1n.iloc[1] == 7
    assert np.isnan(d1n.iloc[2])


def test_d1n_constancy_groups():
    # card 1: D1n constant (7); card 2: D1n 7 and 8 (jitter); card 3: 7 and 20 (multi)
    day = np.array([10, 12, 10, 12, 10, 25]) * 86400
    df = pd.DataFrame(
        {
            "card1": [1, 1, 2, 2, 3, 3],
            "D1": [3, 5, 3, 4, 3, 5],
            "TransactionAmt": 1.0,
            "TransactionDT": day,
        }
    )
    cfg = _cfg(
        {
            "H": {"columns": ["card1"]},
            "I": {"columns": ["card1", "D1n"], "na_level": ["D1n"]},
        }
    )
    cfg["constancy"] = {"levels": ["H", "I"], "tolerance_days": 1}
    _, keys = entity.compare_candidates(df, "TransactionDT", 0.5, cfg)
    work = entity.build_work_frame(df, "TransactionDT", cfg)
    out = entity.d1n_constancy(work, keys, cfg)
    base = out[(out["entity_level"] == "H") & (out["scope"] == "all")].set_index("d1n_group")
    assert list(base["n_entities"]) == [1, 1, 1]  # single, jitter, multi
    split = out[out["entity_level"] == "I"]
    assert (split[split["d1n_group"] != "single"]["n_entities"] == 0).all()


def test_run_profile_writes_outputs(frame, tmp_path):
    settings = load_settings()
    stats = {"transaction_rows": len(frame)}
    res = run_profile(frame, stats, tmp_path / "p", tmp_path / "f", settings)
    for name in [
        "column_schema",
        "missing",
        "outliers",
        "distributions",
        "rare_categories",
        "column_relations",
        "entity_patterns",
        "temporal",
    ]:
        assert (tmp_path / "p" / f"{name}.parquet").exists(), name
    assert (tmp_path / "p" / "summary.md").exists()
    assert (tmp_path / "f" / "entity_size_distribution.png").exists()
    assert len(res["schema"]) == frame.shape[1] + 1
    cands = set(res["entity"]["candidate"])
    assert {"A_card1", "B_card1_addr1", "H_card1_addr1_na_level"} <= cands
    assert "REF_card_full_addr1" not in cands  # constancy-only reference
