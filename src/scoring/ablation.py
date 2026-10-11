"""Ablation / comparison tables. Takes an evaluator callable; reads no labels itself."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.scoring.aggregation import (
    CorrelationWeighted,
    MaxAggregator,
    NoisyOrAggregator,
    WeightedAverage,
)

Evaluator = Callable[[pd.Series], dict[str, float]]


def ablation_table(
    holdout: dict[str, pd.Series],
    fit: dict[str, pd.Series],
    weights: dict[str, float],
    evaluate: Evaluator,
    alt_multivariate: pd.Series | None = None,
) -> pd.DataFrame:
    """Metrics of the main aggregate, each layer alone, leave-one-layer-out, IF-full, and
    alternative aggregators.

    holdout / fit: normalized layer scores of the holdout / fit rows. `evaluate` maps a score
    Series to a metric dict (src.evaluation). Leave-one-out renormalizes the remaining weights.
    """
    avg = WeightedAverage(weights)
    rows: list[tuple[str, str, pd.Series]] = [
        ("main", "weighted average (config weights)", avg.aggregate(holdout))
    ]
    for layer, s in holdout.items():
        rows.append(("single layer", layer, s))
    for layer in holdout:
        rest = {k: v for k, v in holdout.items() if k != layer}
        rows.append(("leave one out", f"without {layer}", avg.aggregate(rest)))
    if alt_multivariate is not None:
        swapped = {**holdout, "multivariate": alt_multivariate}
        rows.append(("variant", "IF-full instead of IF-core", avg.aggregate(swapped)))
    corr = CorrelationWeighted().fit(fit)
    rows.append(("aggregator", "B: correlation-weighted", corr.aggregate(holdout)))
    rows.append(("aggregator", "max", MaxAggregator().aggregate(holdout)))
    rows.append(("aggregator", "noisy-OR", NoisyOrAggregator().aggregate(holdout)))
    out = []
    for group, name, score in rows:
        out.append({"group": group, "variant": name, **evaluate(score)})
    table = pd.DataFrame(out)
    table.attrs["corr_weights"] = corr.weights
    return table
