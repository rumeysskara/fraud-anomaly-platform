"""ScoringService: fit on the fit set, batch = online, persistence, container provider."""

import numpy as np
import pandas as pd

from src.detection import LAYERS
from src.detection.aux import build_aux
from src.scoring.service import NORM_COL, RAW_COL, ScoringService

FIT = 400


def _service(features, cfg, catalog, weights) -> ScoringService:
    svc = ScoringService.fit(features.iloc[:FIT], cfg, catalog, weights)
    svc.build_hour_store(features.iloc[:500])
    return svc


def test_batch_output_columns_ranges_and_contributions(features, cfg, catalog, weights):
    out = _service(features, cfg, catalog, weights).score_batch(features)
    for layer in LAYERS:
        assert out[f"{layer}_score"].between(0, 1).all()
        assert f"raw_{layer}" in out.columns and f"contrib_{layer}" in out.columns
    assert out[RAW_COL].between(0, 1).all() and out[NORM_COL].between(0, 1).all()
    contrib = out[[f"contrib_{n}" for n in LAYERS]].sum(axis=1)
    assert np.allclose(contrib, out[RAW_COL])
    # weighted average of the layer scores with the config weights
    manual = sum(weights[n] * out[f"{n}_score"] for n in LAYERS)
    assert np.allclose(manual, out[RAW_COL])


def test_score_one_equals_batch_row(features, cfg, catalog, weights):
    svc = _service(features, cfg, catalog, weights)
    batch = svc.score_batch(features)
    i = 500
    record = {k: (None if pd.isna(v) else v) for k, v in features.iloc[i].to_dict().items()}
    res = svc.score_one(record)
    assert np.isclose(res.raw_score, batch[RAW_COL].iloc[i])
    assert np.isclose(res.score, batch[NORM_COL].iloc[i])
    for layer in LAYERS:
        assert np.isclose(res.layer_scores[layer], batch[f"{layer}_score"].iloc[i])
    assert {e.source for e in res.explanations} == set(LAYERS)
    assert all(e.message for e in res.explanations)


def test_fit_uses_only_the_fit_rows(features, cfg, catalog, weights):
    a = ScoringService.fit(features.iloc[:FIT], cfg, catalog, weights)
    changed = features.copy()
    changed.iloc[FIT:, changed.columns.get_loc("amt_log")] = 40.0  # holdout rows altered
    b = ScoringService.fit(changed.iloc[:FIT], cfg, catalog, weights)
    fit_rows = features.iloc[:FIT]
    assert np.allclose(a.score_batch(fit_rows)[RAW_COL], b.score_batch(fit_rows)[RAW_COL])
    xa, xb = (s.detectors["column"].normalizer.xp_ for s in (a, b))
    assert xa.tolist() == xb.tolist()


def test_save_and_load_roundtrip(tmp_path, features, cfg, catalog, weights):
    svc = _service(features, cfg, catalog, weights)
    svc.save(tmp_path)
    loaded = ScoringService.load(tmp_path)
    assert np.allclose(
        svc.score_batch(features, online=True)[NORM_COL],
        loaded.score_batch(features, online=True)[NORM_COL],
    )
    table = pd.read_parquet(tmp_path / "normalization_table.parquet")
    assert set(table["layer"]) == {*LAYERS, "aggregate"}
    assert (table.groupby("layer").size() == 1001).all()


def test_build_aux_key_and_device_flag():
    raw = pd.DataFrame({"card1": [1, 1], "addr1": [10.0, np.nan], "DeviceInfo": ["x", None]})
    aux = build_aux(raw)
    assert aux["entity_key"].nunique() == 2 and aux["has_device"].tolist() == [1, 0]


def test_container_provider_loads_saved_service(tmp_path, features, cfg, catalog, weights):
    from dependency_injector import providers

    from src.container import Container

    _service(features, cfg, catalog, weights).save(tmp_path)
    container = Container()
    container.scoring_service.override(providers.Singleton(ScoringService.load, tmp_path))
    assert isinstance(container.scoring_service(), ScoringService)
