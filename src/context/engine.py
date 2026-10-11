"""ContextAdjustEngine: config-driven context adjustment of the Step 5 anomaly score.

Batch (adjust_batch) and single record (adjust_one) run the same vectorized core (`_core`), K-01.
Chain: layer_weight rules -> multiplicative rules -> bounds on the total factor
-> card-testing guard -> clip to [0, 1].
Every applied rule is reported with its id, factor and rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.context.conditions import clause_features, eval_condition
from src.context.config import ContextConfig, RuleSpec
from src.context.derive import DERIVED_COLUMNS, add_derived, layer_columns, required_columns
from src.context.params import ContextParams
from src.core.interfaces import ContextAdjuster, Normalizer
from src.core.types import AdjustedResult, Explanation
from src.scoring.aggregation import WeightedAverage

RAW_SCORE = "raw_score"
ADJUSTED_SCORE = "adjusted_score"
TOTAL = "adjustment_total"
UNBOUNDED = "adjustment_unbounded"
GUARD_ACTIVE = "guard_active"
APPLIED = "applied_adjustments"
FACTOR_PREFIX = "factor_"
FACTOR_EPS = 1e-9


@dataclass
class CoreResult:
    """Arrays produced by the shared core for n rows and R rules."""

    rules: list[RuleSpec]
    factors: np.ndarray  # (n, R), 1.0 where a rule did not apply
    unbounded: np.ndarray  # product of all factors
    total: np.ndarray  # after bounds and guard
    guard: np.ndarray  # card-testing guard condition
    adjusted: np.ndarray


class ContextAdjustEngine(ContextAdjuster):
    """Context adjuster driven by configs/context.yaml.

    Args:
        cfg: parsed context config (rules, bounds, guard).
        params: values learned on the fit set (q90 amount, dominant addr2).
        weights: Step 5 layer weights (configs/weights.yaml), used by C5 and dominant_layer.
        aggregate_normalizer: Step 5 fit quantile table of the aggregate
            (raw_anomaly_score -> anomaly_score_norm).
    """

    def __init__(
        self,
        cfg: ContextConfig,
        params: ContextParams,
        weights: dict[str, float],
        aggregate_normalizer: Normalizer,
    ) -> None:
        self.cfg = cfg
        self.params = params
        self.weights = dict(weights)
        self.normalizer = aggregate_normalizer
        self._check_config()

    def _check_config(self) -> None:
        """Every condition must read a known column and every layer must exist."""
        known = set(required_columns(self.weights)) | set(DERIVED_COLUMNS)
        conditions = [r.condition for r in self.cfg.rules] + [self.cfg.guard.condition]
        for cond in conditions:
            unknown = set(clause_features(cond)) - known
            if unknown:
                raise ValueError(f"context condition uses unknown columns {sorted(unknown)}")
        for rule in self.cfg.rules:
            if rule.type == "layer_weight" and rule.layer not in self.weights:
                raise ValueError(f"rule {rule.id}: unknown layer {rule.layer}")

    def with_config(self, cfg: ContextConfig) -> ContextAdjustEngine:
        """Same params/weights with another config variant (ablation)."""
        return ContextAdjustEngine(cfg, self.params, self.weights, self.normalizer)

    # ---- shared core -------------------------------------------------------------------------

    def normalized_aggregate(self, df: pd.DataFrame, weights: dict[str, float]) -> np.ndarray:
        """Step 5 weighted average with `weights`, mapped through the Step 5 aggregate table."""
        scores = {n: df[f"{n}_score"].astype("float64") for n in weights}
        agg = WeightedAverage(weights).aggregate(scores).to_numpy()
        return self.normalizer.transform(agg)

    def _layer_weight_factor(self, df: pd.DataFrame, rule: RuleSpec) -> np.ndarray:
        """Factor = norm(aggregate with the layer weight scaled) / norm(original aggregate)."""
        new_w = dict(self.weights)
        new_w[rule.layer] = new_w[rule.layer] * rule.weight_multiplier
        before = self.normalized_aggregate(df, self.weights)
        after = self.normalized_aggregate(df, new_w)
        factor = np.where(before > 0, after / np.where(before > 0, before, 1.0), 1.0)
        if rule.only_if_lowers:
            factor = np.minimum(factor, 1.0)
        if self.cfg.use_bounds:
            # one rule can never move the score further than the total bounds allow
            factor = np.clip(factor, self.cfg.min_total, self.cfg.max_total)
        missing = df[layer_columns(self.weights)].isna().any(axis=1).to_numpy()
        return np.where(missing, 1.0, factor)

    def _core(self, df: pd.DataFrame, raw: np.ndarray) -> CoreResult:
        """Apply the rule chain to rows of df (raw = anomaly_score_norm of the same rows)."""
        missing = [c for c in required_columns(self.weights) if c not in df.columns]
        if missing:
            raise KeyError(f"context input is missing columns {missing}")
        data = add_derived(df, self.weights, self.cfg.derived)
        rules = self.cfg.active_rules()
        n = len(data)
        factors = np.ones((n, len(rules)))
        for j, rule in enumerate(rules):
            mask = eval_condition(data, rule.condition, self.params)
            if rule.type == "layer_weight":
                factors[:, j] = np.where(mask, self._layer_weight_factor(data, rule), 1.0)
            else:
                factors[:, j] = np.where(mask, rule.factor, 1.0)
        unbounded = factors.prod(axis=1)
        total = unbounded.copy()
        if self.cfg.use_bounds:
            total = np.clip(total, self.cfg.min_total, self.cfg.max_total)
        guard = eval_condition(data, self.cfg.guard.condition, self.params)
        if self.cfg.use_guard:
            total = np.where(guard, np.maximum(total, self.cfg.guard.min_total), total)
        raw = np.asarray(raw, dtype="float64")
        adjusted = np.clip(raw * total, self.cfg.clip_min, self.cfg.clip_max)
        return CoreResult(rules, factors, unbounded, total, guard, adjusted)

    def _entries(self, res: CoreResult, i: int) -> list[dict[str, Any]]:
        """Applied adjustments of row i: rules, then bounds/guard corrections if they changed it."""
        out = [
            {"id": r.id, "name": r.name, "factor": float(res.factors[i, j]), "reason": r.rationale}
            for j, r in enumerate(res.rules)
            if abs(res.factors[i, j] - 1.0) > FACTOR_EPS
        ]
        bounded = res.unbounded[i]
        if self.cfg.use_bounds:
            bounded = float(np.clip(bounded, self.cfg.min_total, self.cfg.max_total))
            if abs(bounded - res.unbounded[i]) > FACTOR_EPS:
                reason = f"total factor limited to [{self.cfg.min_total}, {self.cfg.max_total}]"
                out.append(
                    {
                        "id": "BOUNDS",
                        "name": "total_factor_bounds",
                        "factor": float(bounded / max(res.unbounded[i], FACTOR_EPS)),
                        "reason": reason,
                    }
                )
        if abs(res.total[i] - bounded) > FACTOR_EPS:
            g = self.cfg.guard
            out.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "factor": float(res.total[i] / bounded),
                    "reason": g.rationale,
                }
            )
        return out

    # ---- public API --------------------------------------------------------------------------

    def adjust_batch(
        self, df: pd.DataFrame, raw_score: pd.Series, explain: bool = True
    ) -> pd.DataFrame:
        """Adjust many rows. Columns: raw_score, adjusted_score, adjustment_total,
        adjustment_unbounded, guard_active, factor_<rule id> and (explain=True) applied_adjustments.
        """
        raw = raw_score.loc[df.index].to_numpy("float64")
        res = self._core(df, raw)
        out = pd.DataFrame(index=df.index)
        out[RAW_SCORE] = raw
        out[ADJUSTED_SCORE] = res.adjusted
        out[TOTAL] = res.total
        out[UNBOUNDED] = res.unbounded
        out[GUARD_ACTIVE] = res.guard.astype("int8")
        for j, rule in enumerate(res.rules):
            out[f"{FACTOR_PREFIX}{rule.id}"] = res.factors[:, j].astype("float32")
        if explain:
            out[APPLIED] = [self._entries(res, i) for i in range(len(df))]
        return out

    def adjust_one(self, record: dict[str, Any], raw_score: float) -> AdjustedResult:
        """Adjust one record (online API) with the same core as adjust_batch."""
        frame = pd.DataFrame([record])
        res = self._core(frame, np.array([raw_score], dtype="float64"))
        entries = self._entries(res, 0)
        explanations = [
            Explanation(
                source="context",
                message=f"{e['id']} {e['name']}: x{e['factor']:.3f}",
                details=e,
            )
            for e in entries
        ]
        explanations.append(
            Explanation(
                source="context",
                message=f"total factor x{res.total[0]:.3f}",
                details={
                    "total": float(res.total[0]),
                    "unbounded": float(res.unbounded[0]),
                    "guard_active": bool(res.guard[0]),
                },
            )
        )
        return AdjustedResult(
            raw_score=float(raw_score),
            adjusted_score=float(res.adjusted[0]),
            applied_rules=[e["id"] for e in entries],
            explanations=explanations,
        )
