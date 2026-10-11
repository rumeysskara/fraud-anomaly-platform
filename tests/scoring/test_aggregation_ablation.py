"""Aggregators and the ablation table on synthetic layer scores."""

import numpy as np
import pandas as pd
import pytest

from src.detection.config import load_weights
from src.scoring.ablation import ablation_table
from src.scoring.aggregation import (
    CorrelationWeighted,
    MaxAggregator,
    NoisyOrAggregator,
    WeightedAverage,
    rank_check,
)


def _scores(n: int = 300) -> dict[str, pd.Series]:
    rng = np.random.default_rng(42)
    base = rng.random(n)
    return {
        "multivariate": pd.Series(base),
        "entity": pd.Series(0.7 * base + 0.3 * rng.random(n)),
        "column": pd.Series(rng.random(n)),
        "temporal": pd.Series(rng.random(n)),
    }


def test_config_weights_sum_to_one_and_match_decision():
    w = load_weights()
    assert abs(sum(w.values()) - 1) < 1e-9
    assert w == {"multivariate": 0.35, "entity": 0.25, "column": 0.20, "temporal": 0.20}


def test_weighted_average_contributions_add_up():
    s, w = _scores(), load_weights()
    avg = WeightedAverage(w)
    contrib = avg.contributions(s)
    assert list(contrib.columns) == [f"contrib_{k}" for k in s]
    assert np.allclose(contrib.sum(axis=1), avg.aggregate(s))
    assert rank_check(avg.aggregate(s))


def test_weights_renormalize_when_a_layer_is_removed():
    s = _scores()
    rest = {k: v for k, v in s.items() if k != "temporal"}
    eff = WeightedAverage(load_weights()).effective_weights(list(rest))
    assert abs(sum(eff.values()) - 1) < 1e-9 and np.isclose(eff["multivariate"], 0.35 / 0.8)


def test_alternative_aggregators():
    s = _scores()
    assert (MaxAggregator().aggregate(s) >= WeightedAverage(load_weights()).aggregate(s)).all()
    assert (NoisyOrAggregator().aggregate(s) >= MaxAggregator().aggregate(s) - 1e-12).all()
    corr = CorrelationWeighted().fit(s)
    assert abs(sum(corr.weights.values()) - 1) < 1e-9
    assert corr.weights["entity"] < corr.weights["temporal"]  # entity is correlated with others


def test_ablation_table_rows_and_label_free_evaluator():
    s = _scores()
    seen = []

    def evaluate(score: pd.Series) -> dict[str, float]:
        seen.append(len(score))
        return {"pr_auc": float(score.mean())}

    table = ablation_table(s, s, load_weights(), evaluate, alt_multivariate=s["entity"])
    assert {"main", "single layer", "leave one out", "variant", "aggregator"} == set(table["group"])
    assert (table["group"] == "leave one out").sum() == 4
    assert "without temporal" in set(table["variant"])
    assert len(table) == 1 + 4 + 4 + 1 + 3 and all(v == 300 for v in seen)


def test_weighted_average_rejects_unknown_layers():
    with pytest.raises(ValueError):
        WeightedAverage({"a": 1.0}).effective_weights(["b"])
