"""Config, container and interface contract tests."""

import pandas as pd
import pytest

from src.container import create_container
from src.core.config import load_settings
from src.core.interfaces import Detector


def test_settings_values():
    s = load_settings()
    assert s["seed"] == 42
    assert s["time"]["reference_date"] == "2017-12-01 00:00:00"
    assert s["split"]["fit_ratio"] == 0.8


def test_container_loads_config():
    c = create_container()
    assert c.config.seed() == 42


def test_detector_is_abstract():
    with pytest.raises(TypeError):
        Detector()  # type: ignore[abstract]


def test_detector_subclass_works():
    class Const(Detector):
        def fit(self, df):
            return self

        def score(self, df):
            return pd.Series(0.5, index=df.index)

        def explain(self, row):
            return {"reason": "constant"}

    assert Const().fit(pd.DataFrame({"a": [1]})).score(pd.DataFrame({"a": [1]})).iloc[0] == 0.5


def test_set_seed_reads_settings():
    import random

    from src.core.config import set_seed

    set_seed()
    a = random.random()
    set_seed(load_settings()["seed"])
    assert random.random() == a
