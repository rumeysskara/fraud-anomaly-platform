"""Batch transform and the online transform_one path must give the same numbers."""

import numpy as np
import pandas as pd

from src.features.history import EntityStore
from tests.features.conftest import to_txn


def _assert_same(online: list[dict], batch: pd.DataFrame) -> None:
    got = pd.DataFrame(online, index=batch.index)[batch.columns]
    np.testing.assert_allclose(
        got.to_numpy("float64"), batch.to_numpy("float64"), rtol=1e-4, atol=1e-2, equal_nan=True
    )


def test_stream_replay_equals_batch(pipe, frame):
    batch = pipe.transform(frame)
    pipe.store = None  # empty store: replay every transaction in time order
    online = [pipe.transform_one(to_txn(r), update=True) for _, r in frame.iterrows()]
    _assert_same(online, batch)


def test_store_snapshot_equals_batch(pipe, frame):
    """History in the store (built from the first 300 rows) gives batch values for later rows."""
    batch = pipe.transform(frame)
    pipe.build_store(frame.iloc[:300])
    online = []
    for _, r in frame.iloc[300:].iterrows():
        online.append(pipe.transform_one(to_txn(r), update=True))
    _assert_same(online, batch.iloc[300:])


def test_store_parquet_roundtrip(pipe, frame, tmp_path):
    store = pipe.build_store(frame)
    path = tmp_path / "entity_profiles.parquet"
    store.to_frame().to_parquet(path)
    loaded = EntityStore.from_frame(pd.read_parquet(path), pipe.stats, pipe.config)
    assert loaded.entities.keys() == store.entities.keys()
    row = to_txn(frame.iloc[-1])
    pipe.store = store
    a = pipe.transform_one(row)
    pipe.store = loaded
    b = pipe.transform_one(row)
    pd.testing.assert_series_equal(pd.Series(a), pd.Series(b))


def test_save_load_pipeline(pipe, frame, tmp_path):
    pipe.save(tmp_path / "p.joblib")
    from src.features import FeaturePipeline

    again = FeaturePipeline.load(tmp_path / "p.joblib")
    pd.testing.assert_frame_equal(pipe.transform(frame), again.transform(frame))


def test_container_has_feature_pipeline_provider():
    from src.container import create_container

    c = create_container()
    assert c.feature_pipeline.provides is not None
