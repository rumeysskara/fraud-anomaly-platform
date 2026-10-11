"""Factory (design pattern) that builds the layer detectors from configs/anomaly.yaml."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from src.detection.base import LayerDetector
from src.detection.column import ColumnDetector
from src.detection.config import seed
from src.detection.entity import EntityDetector
from src.detection.multivariate import MultivariateDetector
from src.detection.temporal import TemporalDetector

LAYERS = ("multivariate", "entity", "column", "temporal")


def multivariate_columns(
    cfg: dict[str, Any], catalog: pd.DataFrame, available: list[str], full: bool = False
) -> list[str]:
    """Input columns of IF-core (or IF-full with V representatives), K-13 / K-18.

    Engineered groups with model_input = true plus passthrough C/D (and V for full), minus the
    always-dropped and lifetime-cumulative columns (windowed velocity columns stay).
    """
    common = cfg["common"]
    drop = set(common["drop_always"] + common["drop_cumulative"])
    core = cfg["multivariate"]["core"]
    patterns = list(core["passthrough_patterns"])
    if full:
        patterns += cfg["multivariate"]["full_extra_patterns"]
    in_groups = catalog["group"].isin(core["groups"]) & catalog["model_input"].astype(bool)
    names = list(catalog.loc[in_groups, "name"])
    names += [n for n in catalog["name"] if any(re.match(p, n) for p in patterns)]
    avail = set(available)
    return [n for n in dict.fromkeys(names) if n not in drop and n in avail]


def build_detector(
    layer: str, cfg: dict[str, Any], catalog: pd.DataFrame, available: list[str], full: bool = False
) -> LayerDetector:
    """Create one (unfitted) layer detector; `full=True` builds the IF-full ablation variant."""
    grid = int(cfg["normalization"]["grid_points"])
    sentinel = list(cfg["common"]["sentinel_to_nan"])
    if layer == "multivariate":
        mv = cfg["multivariate"]
        return MultivariateDetector(
            name="multivariate_full" if full else "multivariate",
            columns=multivariate_columns(cfg, catalog, available, full),
            sentinel_cols=sentinel,
            pre_cfg=cfg["preprocess"],
            if_cfg=mv["isolation_forest"],
            seed=seed(),
            grid_points=grid,
            explain_top=int(mv["explain_top"]),
        )
    if layer == "column":
        col = cfg["column"]
        return ColumnDetector(
            col["columns"], int(col["top_k"]), int(col["discrete_max_unique"]), sentinel, grid
        )
    if layer == "entity":
        ent = cfg["entity"]
        return EntityDetector(ent["shrinkage_k"], ent["count_column"], grid)
    if layer == "temporal":
        return TemporalDetector(cfg["temporal"], sentinel, grid)
    raise ValueError(f"unknown layer {layer}")


def build_all(
    cfg: dict[str, Any], catalog: pd.DataFrame, available: list[str]
) -> dict[str, LayerDetector]:
    """Create the four main layer detectors."""
    return {layer: build_detector(layer, cfg, catalog, available) for layer in LAYERS}
