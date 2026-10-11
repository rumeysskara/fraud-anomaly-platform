"""fit / score / explain of the four layers on the synthetic frame."""

import numpy as np

from src.core.interfaces import Detector
from src.detection import LAYERS, build_all, build_detector
from src.detection.factory import multivariate_columns
from src.detection.hour_history import HourStore, hour_rarity, past_hour_counts

FIT = 400


def _fit_all(features, cfg, catalog):
    dets = build_all(cfg, catalog, list(features.columns))
    for d in dets.values():
        d.fit(features.iloc[:FIT])
    return dets


def test_every_layer_is_a_detector_with_scores_in_unit_range(features, cfg, catalog):
    dets = _fit_all(features, cfg, catalog)
    assert set(dets) == set(LAYERS)
    for name, det in dets.items():
        assert isinstance(det, Detector)
        s = det.score(features)
        assert s.index.equals(features.index) and s.between(0, 1).all(), name
        assert s.std() > 0.1, name  # not degenerate


def test_explain_returns_layer_details_and_scores(features, cfg, catalog):
    dets = _fit_all(features, cfg, catalog)
    row = features.iloc[450]
    for name, det in dets.items():
        info = det.explain(row)
        assert info["layer"] == name and 0 <= info["score"] <= 1 and "raw_score" in info
    assert len(dets["column"].explain(row)["top_columns"]) == cfg["column"]["top_k"]
    top = dets["multivariate"].explain(row)["top_features"]
    assert len(top) == cfg["multivariate"]["explain_top"] and "contribution" in top[0]
    subs = dets["temporal"].explain(row)["subscores"]
    assert set(subs) == set(cfg["temporal"]["subscore_weights"])


def test_column_layer_flags_an_extreme_column_and_uses_top_k_mean(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["column"]
    odd = features.iloc[[450]].copy()
    odd["amt_log"] = 25.0
    cols = det.column_scores(odd).iloc[0]
    assert cols.idxmax() == "amt_log" or cols["amt_log"] >= cols.nlargest(3).iloc[-1]
    expected = cols.nlargest(cfg["column"]["top_k"]).mean()
    assert np.isclose(det.raw_score(odd)[0], expected)
    assert det.raw_score(odd)[0] > det.raw_score(features.iloc[[450]])[0]


def test_multivariate_input_exclusions(features, cfg, catalog):
    core = multivariate_columns(cfg, catalog, list(features.columns))
    full = multivariate_columns(cfg, catalog, list(features.columns), full=True)
    banned = set(cfg["common"]["drop_always"] + cfg["common"]["drop_cumulative"])
    assert not banned & set(full)
    # windowed velocity columns are not cumulative and must stay in the multivariate input
    assert {"ent_cnt_1h", "ent_cnt_24h", "ent_sum_1h"} <= set(core)
    assert "V1" not in core and "V1" in full
    assert "C13" in core and "D4" in core


def test_multivariate_is_seeded_and_flags_outliers(features, cfg, catalog):
    a = build_detector("multivariate", cfg, catalog, list(features.columns)).fit(features[:FIT])
    b = build_detector("multivariate", cfg, catalog, list(features.columns)).fit(features[:FIT])
    assert np.allclose(a.raw_score(features), b.raw_score(features))
    odd = features.iloc[[450]].copy()
    odd["C13"], odd["amt_log"] = 500.0, 30.0
    assert a.raw_score(odd)[0] > a.raw_score(features.iloc[[450]])[0]


def test_entity_shrinkage_weight_and_first_transaction(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["entity"]
    parts = det.parts(features)
    n = features["ent_txn_count"]
    assert np.allclose(parts["w"], n / (n + cfg["entity"]["shrinkage_k"]))
    first = features["ent_txn_count"] == 0
    assert (parts.loc[first, "w"] == 0).all()
    assert np.allclose(parts.loc[first, "blend"], parts.loc[first, "global_part"])


def test_entity_uses_global_std_when_std_is_zero(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["entity"]
    row = features.iloc[[450]].copy()
    row["ent_txn_count"], row["ent_avg_amt"], row["ent_std_amt"] = 5, 10.0, 0.0
    row["amt_log"] = np.log1p(10.0 + det.global_std_)
    z = det._signals(row)["amount_z"][0]
    assert np.isclose(z, 1.0, atol=1e-3)


def test_entity_raises_score_for_amount_far_from_own_history(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["entity"]
    base = features.iloc[[450]].copy()
    base["ent_txn_count"], base["ent_avg_amt"], base["ent_std_amt"] = 30, 20.0, 5.0
    base["amt_ratio_to_ent_avg"], base["amt_log"] = 1.0, np.log1p(20.0)
    far = base.copy()
    far["amt_log"], far["amt_ratio_to_ent_avg"] = np.log1p(900.0), 45.0
    assert det.raw_score(far)[0] > det.raw_score(base)[0]


def test_hour_history_is_past_only_and_shrinks():
    keys = np.array(["a", "a", "b", "a", "b"])
    hours = np.array([3, 3, 3, 5, 3])
    same, total = past_hour_counts(keys, hours)
    assert same.tolist() == [0, 1, 0, 0, 1] and total.tolist() == [0, 1, 0, 2, 1]
    g = np.full(24, 1 / 24)
    low_n = hour_rarity(np.array([0.0]), np.array([0.0]), g, np.array([3]), 5.0)[0]
    assert np.isclose(low_n, -np.log10(1 / 24))  # no history -> global share
    habitual = hour_rarity(np.array([40.0]), np.array([40.0]), g, np.array([3]), 5.0)[0]
    unusual = hour_rarity(np.array([0.0]), np.array([40.0]), g, np.array([3]), 5.0)[0]
    assert habitual < low_n < unusual


def test_hour_store_matches_expanding_history():
    keys = np.array(["a", "a", "b", "a", "b", "a"])
    hours = np.array([3, 3, 3, 5, 3, 3])
    same, total = past_hour_counts(keys, hours)
    store = HourStore.from_arrays(keys[:5], hours[:5], 24)
    s, t = store.lookup(keys[5:], hours[5:])
    assert (s[0], t[0]) == (same[5], total[5])
    unknown = store.lookup(np.array(["zzz"]), np.array([3]))
    assert unknown[0][0] == 0.0 and unknown[1][0] == 0.0


def test_temporal_online_equals_batch_with_store(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["temporal"]
    batch = det.raw_score(features)
    det.build_store(features.iloc[:500])
    online = det.raw_score_online(features.iloc[500:501])  # history = exactly the first 500 rows
    assert np.allclose(online, batch[500:501])


def test_temporal_velocity_and_short_gap_raise_the_score(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["temporal"]
    base = features.iloc[[450]].copy()
    base["ent_cnt_1h"], base["ent_cnt_24h"], base["ent_sum_1h"] = 0, 0, 0.0
    base["time_since_last_txn"], base["avg_inter_arrival"] = 40000.0, 40000.0
    burst = base.copy()
    burst["ent_cnt_1h"], burst["ent_cnt_24h"], burst["ent_sum_1h"] = 30, 60, 5000.0
    burst["time_since_last_txn"] = 2.0
    sb, sx = det.subscores(base).iloc[0], det.subscores(burst).iloc[0]
    assert sx["velocity"] > sb["velocity"] and sx["inter_arrival"] > sb["inter_arrival"]


def test_sentinel_means_missing_not_a_short_gap(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["temporal"]
    row = features.iloc[[450]].copy()
    row["time_since_last_txn"], row["avg_inter_arrival"] = -1.0, -1.0
    assert det.subscores(row)["inter_arrival"].iloc[0] == 0.0


def test_future_rows_do_not_change_past_temporal_scores(features, cfg, catalog):
    det = _fit_all(features, cfg, catalog)["temporal"]
    full = det.raw_score(features)
    prefix = det.raw_score(features.iloc[:450])
    assert np.allclose(full[:450], prefix)
