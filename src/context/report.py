"""Label-free report helpers for Step 6 (rule coverage, alarm composition, ablation variants).

Label-based metrics are computed only by src/evaluation (called from scripts/run_context.py).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

from src.context.config import ContextConfig
from src.context.engine import ADJUSTED_SCORE, FACTOR_PREFIX, ContextAdjustEngine


def tie_break_order(tiebreak: pd.Series) -> pd.Index:
    """Index sorted by the tie-break score (descending, stable).

    adjusted_score saturates at 1.0 for many rows (multiplicative boosts + clip), so a top-k cut
    would otherwise pick among equal scores by TransactionID. Ordering rows by the unnormalized
    Step 5 score first makes the stable top-k break ties by it (the same order for every variant).
    """
    return tiebreak.sort_values(ascending=False, kind="stable").index


def alarm_mask(score: pd.Series, budget: float, tiebreak: pd.Series | None = None) -> pd.Series:
    """True for the top `budget` fraction of rows; ties broken by `tiebreak` (then by order)."""
    k = math.ceil(budget * len(score))
    ordered = score.loc[tie_break_order(tiebreak)] if tiebreak is not None else score
    top = ordered.index[np.argsort(-ordered.to_numpy(), kind="stable")[:k]]
    return pd.Series(score.index.isin(top), index=score.index)


def rule_coverage(
    result: pd.DataFrame, cfg: ContextConfig, parts: dict[str, pd.Index]
) -> pd.DataFrame:
    """Share of rows where each rule changed the score, per part (fit / holdout)."""
    rows = []
    for rule in cfg.rules:
        col = f"{FACTOR_PREFIX}{rule.id}"
        row: dict[str, object] = {"id": rule.id, "name": rule.name, "type": rule.type}
        for part, idx in parts.items():
            f = result.loc[idx, col].to_numpy("float64")
            applied = np.abs(f - 1.0) > 1e-9
            row[f"{part}_share"] = float(applied.mean())
            row[f"{part}_mean_factor_when_applied"] = (
                float(f[applied].mean()) if applied.any() else 1.0
            )
        rows.append(row)
    row = {"id": cfg.guard.id, "name": cfg.guard.name, "type": "guard (condition true)"}
    for part, idx in parts.items():
        row[f"{part}_share"] = float(result.loc[idx, "guard_active"].mean())
    rows.append(row)
    return pd.DataFrame(rows)


def alarm_composition(
    before: pd.Series,
    after: pd.Series,
    inputs: pd.DataFrame,
    guard: pd.Series,
    budgets: list[float],
    long_history: int,
    tiebreak: pd.Series | None = None,
) -> pd.DataFrame:
    """Label-free alarm profile before/after: long-history entities, first-seen rows, guard rows."""
    long_hist = inputs["ent_txn_count"] >= long_history
    first = inputs["ent_txn_count"] == 0
    rows = []
    for b in budgets:
        m_before = alarm_mask(before, b, tiebreak)
        m_after = alarm_mask(after, b, tiebreak)
        for name, m in (("before", m_before), ("after", m_after)):
            rows.append(
                {
                    "budget": b,
                    "score": name,
                    "alarms": int(m.sum()),
                    f"alarms_ent_txn_count_ge_{long_history}": int((m & long_hist).sum()),
                    "alarms_first_seen": int((m & first).sum()),
                    "alarms_guard_active": int((m & guard.astype(bool)).sum()),
                    "left_alarm_set": int((m_before & ~m).sum()),
                }
            )
    return pd.DataFrame(rows)


def ablation_variants(cfg: ContextConfig) -> list[tuple[str, str, ContextConfig]]:
    """(kind, label, config) for: full, leave-one-group-out, only-one-group, no guard, no bounds."""
    groups = cfg.groups()
    out = [("full", "all rules", cfg)]
    for g in groups:
        out.append(("leave_one_out", f"without {g}", cfg.variant(disabled={g})))
    for g in groups:
        others = set(groups) - {g}
        out.append(("only_one", f"only {g}", cfg.variant(disabled=others)))
    out.append(("guard", "without guard G1", cfg.variant(use_guard=False)))
    out.append(("bounds", "without bounds", cfg.variant(use_bounds=False)))
    out.append(
        ("bounds", "without guard and bounds", cfg.variant(use_guard=False, use_bounds=False))
    )
    return out


def run_ablation(
    engine: ContextAdjustEngine,
    inputs: pd.DataFrame,
    raw_score: pd.Series,
    evaluate: Callable[[pd.Series], dict[str, float]],
) -> pd.DataFrame:
    """Evaluate every variant with the given (label-aware) evaluate callback.

    `evaluate` is passed in by the script; this module never reads the label.
    """
    rows = [{"kind": "baseline", "variant": "no context (raw)", **evaluate(raw_score)}]
    for kind, label, cfg in ablation_variants(engine.cfg):
        res = engine.with_config(cfg).adjust_batch(inputs, raw_score, explain=False)
        rows.append({"kind": kind, "variant": label, **evaluate(res[ADJUSTED_SCORE])})
    return pd.DataFrame(rows)
