"""ScoringService: fits the layers, scores batches and single records with the same code."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from src.core.types import Explanation, ScoreResult
from src.detection.aux import ENTITY_KEY
from src.detection.base import LayerDetector
from src.detection.factory import LAYERS, build_all
from src.detection.normalization import QuantileNormalizer
from src.detection.temporal import TemporalDetector
from src.scoring.aggregation import WeightedAverage

logger = logging.getLogger(__name__)

META_FILE = "scoring_meta.joblib"
RAW_COL = "raw_anomaly_score"
NORM_COL = "anomaly_score_norm"


class ScoringService:
    """Four layer detectors + weighted average + aggregate normalizer.

    Outputs per row: raw_<layer> (unbounded), <layer>_score ([0,1]), contrib_<layer>,
    raw_anomaly_score (weighted mean of the layer scores, [0,1]) and anomaly_score_norm
    (the aggregate mapped through its own fit quantile table).
    """

    def __init__(
        self,
        detectors: dict[str, LayerDetector],
        weights: dict[str, float],
        aggregate_normalizer: QuantileNormalizer | None = None,
    ) -> None:
        self.detectors = detectors
        self.aggregator = WeightedAverage(weights)
        self.aggregate_normalizer = aggregate_normalizer or QuantileNormalizer()

    @classmethod
    def fit(
        cls,
        fit_df: pd.DataFrame,
        cfg: dict[str, Any],
        catalog: pd.DataFrame,
        weights: dict[str, float],
    ) -> ScoringService:
        """Fit all layers (and the aggregate normalizer) on the fit set only."""
        detectors = build_all(cfg, catalog, list(fit_df.columns))
        for name, det in detectors.items():
            logger.info("fit layer %s", name)
            det.fit(fit_df)
        service = cls(detectors, weights)
        grid = int(cfg["normalization"]["grid_points"])
        agg = service.score_batch(fit_df, aggregate_only=True)[RAW_COL]
        service.aggregate_normalizer = QuantileNormalizer(grid).fit(agg.to_numpy())
        return service

    def layer_scores(self, df: pd.DataFrame, online: bool = False) -> pd.DataFrame:
        """raw_<layer> and <layer>_score for every layer."""
        out: dict[str, Any] = {}
        for name, det in self.detectors.items():
            raw = det.raw_score_online(df) if online else det.raw_score(df)
            out[f"raw_{name}"] = raw
            out[f"{name}_score"] = det.normalizer.transform(raw)
        return pd.DataFrame(out, index=df.index)

    def score_batch(
        self, df: pd.DataFrame, online: bool = False, aggregate_only: bool = False
    ) -> pd.DataFrame:
        """Layer scores, contributions, raw aggregate and normalized aggregate for many rows."""
        layers = self.layer_scores(df, online)
        scores = {n: layers[f"{n}_score"] for n in self.detectors}
        contrib = self.aggregator.contributions(scores)
        agg = contrib.sum(axis=1).clip(0.0, 1.0)
        out = pd.concat([layers, contrib], axis=1)
        out[RAW_COL] = agg
        if not aggregate_only:
            out[NORM_COL] = self.aggregate_normalizer.transform(agg.to_numpy())
        return out

    def score_one(self, features: dict[str, Any]) -> ScoreResult:
        """Score one record (feature dict + entity_key / has_device) with the batch code path."""
        frame = pd.DataFrame([features])
        for col in frame.columns:
            if col != ENTITY_KEY:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        row = self.score_batch(frame, online=True).iloc[0]
        layer_scores = {n: float(row[f"{n}_score"]) for n in self.detectors}
        details = {n: d.explain(frame.iloc[0]) for n, d in self.detectors.items()}
        explanations = [
            Explanation(source=n, message=_message(n, det), details=det)
            for n, det in details.items()
        ]
        return ScoreResult(
            score=float(row[NORM_COL]),
            raw_score=float(row[RAW_COL]),
            layer_scores=layer_scores,
            explanations=explanations,
        )

    def build_hour_store(self, df: pd.DataFrame) -> None:
        """Persist the entity-hour history of all rows seen so far (online temporal state)."""
        temporal = self.detectors.get("temporal")
        if isinstance(temporal, TemporalDetector):
            temporal.build_store(df)

    def normalization_table(self) -> pd.DataFrame:
        """All quantile tables in one frame (layer, level, raw_value)."""
        parts = []
        for name, det in self.detectors.items():
            parts.append(det.normalizer.table_.assign(layer=name))
        parts.append(self.aggregate_normalizer.table_.assign(layer="aggregate"))
        return pd.concat(parts, ignore_index=True)[["layer", "level", "raw_value"]]

    def save(self, directory: Path) -> None:
        """Write every fitted detector, the weights and the normalization tables."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, det in self.detectors.items():
            joblib.dump(det, directory / f"{name}.joblib")
        meta = {
            "layers": list(self.detectors),
            "weights": self.aggregator.weights,
            "aggregate_normalizer": self.aggregate_normalizer,
        }
        joblib.dump(meta, directory / META_FILE)
        self.normalization_table().to_parquet(directory / "normalization_table.parquet")

    @classmethod
    def load(cls, directory: Path) -> ScoringService:
        """Load a saved service (no training happens)."""
        meta = joblib.load(directory / META_FILE)
        detectors = {n: joblib.load(directory / f"{n}.joblib") for n in meta["layers"]}
        return cls(detectors, meta["weights"], meta["aggregate_normalizer"])


def _message(layer: str, detail: dict[str, Any]) -> str:
    """One-line human-readable summary of a layer explanation."""
    score = f"{detail['score']:.2f}"
    if layer == "column":
        cols = ", ".join(c["column"] for c in detail["top_columns"])
        return f"column layer {score}: most unusual columns {cols}"
    if layer == "multivariate":
        feats = ", ".join(f["feature"] for f in detail["top_features"][:3])
        return f"multivariate layer {score}: largest contributions {feats}"
    if layer == "entity":
        return (
            f"entity layer {score}: history weight {detail['weight_entity']:.2f} "
            f"(entity part {detail['entity_part']:.2f}, global part {detail['global_part']:.2f})"
        )
    return f"temporal layer {score}: strongest sub-score {detail['top_subscore']}"


__all__ = ["LAYERS", "NORM_COL", "RAW_COL", "ScoringService"]
