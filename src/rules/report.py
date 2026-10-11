"""Label-free report helpers for Step 7 (coverage, decision mix, score effect, examples)."""

from __future__ import annotations

import pandas as pd

from src.rules.engine import ADJUSTED_UNCLIPPED, FINAL_UNCLIPPED, HIT_PREFIX
from src.rules.schema import Rule


def concentration(hit: pd.Series, entity: pd.Series, top: int = 5) -> dict[str, object]:
    """Label-free health metric: how much of a rule's hits come from its busiest entities."""
    keys = entity[hit.astype(bool)]
    if keys.empty:
        return {"top1_entity": None, "top1_entity_share": 0.0, f"top{top}_entity_share": 0.0}
    counts = keys.value_counts()
    return {
        "top1_entity": str(counts.index[0]),
        "top1_entity_share": float(counts.iloc[0] / len(keys)),
        f"top{top}_entity_share": float(counts.iloc[:top].sum() / len(keys)),
    }


def rule_coverage(
    result: pd.DataFrame, rules: list[Rule], parts: dict[str, pd.Index], entity: pd.Series
) -> pd.DataFrame:
    """Per rule and part: hits (before/after cooldown), share, applied, suppressed, winning and
    the entity concentration of the hits (label-free)."""
    rows = []
    for rule in rules:
        col = f"{HIT_PREFIX}{rule.id}"
        row = {
            "id": rule.id,
            "name": rule.name,
            "priority": rule.priority,
            "severity": rule.severity,
            "decision": rule.action.decision,
            "risk_boost": rule.action.risk_boost,
        }
        for part, idx in parts.items():
            sub = result.loc[idx]
            hits = int(sub[col].sum()) if col in sub else 0
            cooled = sub["cooldown_rules"].map(lambda x, r=rule.id: r in x)
            row[f"{part}_hits_before_cooldown"] = hits + int(cooled.sum())
            row[f"{part}_hits"] = hits
            row[f"{part}_share"] = hits / max(len(sub), 1)
            row[f"{part}_applied"] = int(
                sub["applied_rules"].map(lambda x, r=rule.id: r in x).sum()
            )
            row[f"{part}_suppressed"] = int(
                sub["suppressed_rules"].map(lambda x, r=rule.id: r in x).sum()
            )
            row[f"{part}_winner"] = int((sub["decision_source"] == rule.id).sum())
            hit = sub[col] == 1 if col in sub else pd.Series(False, index=sub.index)
            for name, value in concentration(hit, entity.loc[idx]).items():
                row[f"{part}_{name}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def decision_distribution(result: pd.DataFrame, parts: dict[str, pd.Index]) -> pd.DataFrame:
    """Counts of final decisions by source kind (rule / score / default) per part."""
    rows = []
    for part, idx in parts.items():
        sub = result.loc[idx]
        kind = sub["decision_source"].where(
            sub["decision_source"].isin(["score", "default"]), "rule"
        )
        counts = sub.groupby([sub["final_decision"], kind]).size()
        for (decision, source), n in counts.items():
            rows.append(
                {
                    "part": part,
                    "final_decision": decision,
                    "source": source,
                    "rows": int(n),
                    "share": n / len(sub),
                }
            )
    return pd.DataFrame(rows)


def conflict_summary(result: pd.DataFrame, idx: pd.Index) -> pd.DataFrame:
    """How often each (winner, suppressed rule) pair occurs on the given rows."""
    sub = result.loc[idx]
    sub = sub[sub["suppressed_rules"].map(len) > 0]
    pairs = [
        (winner, lost)
        for winner, lost_list in zip(sub["decision_source"], sub["suppressed_rules"], strict=True)
        for lost in lost_list
    ]
    if not pairs:
        return pd.DataFrame(columns=["winner", "suppressed", "rows"])
    table = pd.DataFrame(pairs, columns=["winner", "suppressed"])
    return table.value_counts().rename("rows").reset_index()


def boost_summary(result: pd.DataFrame, idx: pd.Index) -> pd.DataFrame:
    """Effect of rules on the score: boosted rows, mean boost, clipped boosts, score stats."""
    sub = result.loc[idx]
    boosted = sub["boost"] != 0
    return pd.DataFrame(
        [
            {
                "rows": len(sub),
                "rows_boosted": int(boosted.sum()),
                "share_boosted": float(boosted.mean()),
                "mean_boost_when_boosted": (
                    float(sub.loc[boosted, "boost"].mean()) if boosted.any() else 0.0
                ),
                "rows_boost_capped": int((sub["boost_raw"] != sub["boost"]).sum()),
                "mean_adjusted_unclipped": float(sub[ADJUSTED_UNCLIPPED].mean()),
                "mean_final_unclipped": float(sub[FINAL_UNCLIPPED].mean()),
                "rows_final_score_eq_1": int((sub["final_score"] >= 1.0).sum()),
            }
        ]
    )


def pick_conflict_examples(
    result: pd.DataFrame, idx: pd.Index, allow_ids: set[str], n: int = 3
) -> list[int]:
    """Label-free pick of rows with suppressed rules.

    One row per distinct (winner > suppressed rules) combination, highest final score first;
    combinations where an allow rule was suppressed come first.
    """
    sub = result.loc[idx]
    sub = sub[sub["suppressed_rules"].map(len) > 0]
    if sub.empty:
        return []
    key = sub["decision_source"] + ">" + sub["suppressed_rules"].map(",".join)
    allow_lost = sub["suppressed_rules"].map(lambda x: bool(allow_ids & set(x)))
    ranked = sub.assign(_key=key, _allow=allow_lost).sort_values(
        ["_allow", FINAL_UNCLIPPED], ascending=[False, False], kind="stable"
    )
    picked = ranked.drop_duplicates("_key").head(n)
    return [int(i) for i in picked.index]
