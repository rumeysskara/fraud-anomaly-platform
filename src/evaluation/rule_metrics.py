"""Labelled metrics for the Step 7 rule engine (reporting only; nothing here tunes a rule).

All functions take the label y as a separate Series (from the loader) and boolean masks or scores
computed without it. y defines the evaluated rows: inputs are aligned with y.loc / .loc[y.index].
"""

from __future__ import annotations

import math

import pandas as pd

from src.evaluation.metrics import evaluate


def _precision(y: pd.Series, mask: pd.Series) -> float:
    return float(y[mask].mean()) if mask.any() else float("nan")


def rule_hit_metrics(
    y: pd.Series, hits: pd.DataFrame, applied: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Per rule (column of hits): hits, coverage, tp, precision, lift = precision / base rate.

    applied (same columns, optional): rows where the rule was applied after conflict resolution.
    """
    base = float(y.mean())
    hits = hits.loc[y.index].astype(bool)
    rows = []
    for rid in hits.columns:
        hit = hits[rid]
        prec = _precision(y, hit)
        row = {
            "id": rid,
            "hits": int(hit.sum()),
            "coverage": float(hit.mean()),
            "tp": int(y[hit].sum()),
            "precision": prec,
            "lift": prec / base if base else float("nan"),
        }
        if applied is not None:
            app = applied.loc[y.index, rid].astype(bool)
            row["applied"] = int(app.sum())
            row["precision_applied"] = _precision(y, app)
        rows.append(row)
    return pd.DataFrame(rows)


def decision_metrics(y: pd.Series, decision: pd.Series) -> pd.DataFrame:
    """Per final decision: rows, tp, fp, precision, lift."""
    base = float(y.mean())
    decision = decision.loc[y.index]
    out = decision.groupby(decision).size().rename("rows").to_frame()
    out["tp"] = y.groupby(decision).sum()
    out["fp"] = out["rows"] - out["tp"]
    out["precision"] = out["tp"] / out["rows"]
    out["lift"] = out["precision"] / base
    return out.rename_axis("final_decision").reset_index()


def budget_table(y: pd.Series, scores: dict[str, pd.Series], budgets: list[float]) -> pd.DataFrame:
    """For every named score: alarms, tp, fp, precision, recall at each budget + PR/ROC-AUC.

    Top-k is stable in the order of y.index (order y beforehand to define the tie-break).
    """
    rows = []
    for name, score in scores.items():
        m = evaluate(y, score.loc[y.index], budgets)
        for b in budgets:
            k = math.ceil(b * len(y))
            fp = int(m[f"fp@{b}"])
            rows.append(
                {
                    "budget": b,
                    "score": name,
                    "alarms": k,
                    "tp": k - fp,
                    "fp": fp,
                    "precision": m[f"precision@{b}"],
                    "recall": m[f"recall@{b}"],
                    "pr_auc": m["pr_auc"],
                    "roc_auc": m["roc_auc"],
                }
            )
    return pd.DataFrame(rows).sort_values("budget", kind="stable", ignore_index=True)


def lift_by_group(y: pd.Series, masks: pd.DataFrame, group: pd.Series) -> pd.DataFrame:
    """Lift of each condition (mask column) inside each group (e.g. ProductCD).

    lift_in_group = precision of the condition in the group / base rate of the group, so a
    condition whose overall lift only comes from the group mix shows lift ~1 inside groups.
    The first rows of every condition use group "ALL" (all rows).
    """
    group = group.loc[y.index].astype(object).fillna("NA")
    all_rows = pd.Series(True, index=y.index)
    masks = masks.loc[y.index].astype(bool)
    base = float(y.mean())
    rows = []
    for name in masks.columns:
        for g in ["ALL", *sorted(group.unique(), key=str)]:
            in_group = all_rows if g == "ALL" else group == g
            hit = masks[name] & in_group
            group_rate = float(y[in_group].mean())
            prec = _precision(y, hit)
            rows.append(
                {
                    "condition": name,
                    "group": g,
                    "group_rows": int(in_group.sum()),
                    "group_base_rate": group_rate,
                    "hits": int(hit.sum()),
                    "precision": prec,
                    "lift_in_group": prec / group_rate if group_rate else float("nan"),
                    "lift_overall": prec / base if base else float("nan"),
                }
            )
    return pd.DataFrame(rows)
