"""RuleEngine: evaluates configurable rules on top of the Step 6 adjusted score.

Batch (parquet) and online (one record, API) use the same functions: add_derived ->
hit_matrix -> decide. A single record is a one-row DataFrame.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pydantic import Field

from src.core.interfaces import RuleEvaluator
from src.core.types import Explanation, RuleResult
from src.rules.conditions import evaluate_condition, resolve_value
from src.rules.cooldown import CooldownStore, apply_cooldown, cooldown_keys
from src.rules.derive import DERIVED_DEPS, add_derived
from src.rules.explain import render_message, to_python
from src.rules.repository import RuleRepository, RuleSettings
from src.rules.resolver import ALLOW_VS_SCORE_REASON, Resolution, resolve
from src.rules.schema import Rule, condition_features, template_fields

ANOMALY = "anomaly_score"  # Step 5 anomaly_score_norm (display only)
ADJUSTED = "adjusted_score"  # Step 6, clipped to [0,1] (display only)
ADJUSTED_UNCLIPPED = "adjusted_score_unclipped"  # Step 6, the score the rules boost
FINAL = "final_score"
FINAL_UNCLIPPED = "final_score_unclipped"
SCORE_COLUMNS = [ANOMALY, ADJUSTED, ADJUSTED_UNCLIPPED]
HIT_PREFIX = "hit_"
COOLDOWN_REASON = "cooldown: aynı entity için son {window} sn içinde zaten tetiklendi"


class RuleEngineResult(RuleResult):
    """RuleResult plus the full explainability output of Step 7."""

    final_decision: str
    decision_source: str  # winning rule id, "score" or "default"
    applied_rules: list[str] = Field(default_factory=list)
    triggered_details: list[dict[str, Any]] = Field(default_factory=list)
    suppressed_rules: list[dict[str, str]] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    anomaly_score: float | None = None
    adjusted_score: float
    adjusted_score_unclipped: float
    boost_total: float = 0.0
    final_score_unclipped: float

    def explain_dict(self) -> dict[str, Any]:
        """JSON-friendly explanation (triggered/suppressed rules, decision, reasons, scores)."""
        return {
            "triggered_rules": self.triggered_details,
            "applied_rules": self.applied_rules,
            "suppressed_rules": self.suppressed_rules,
            "final_decision": self.final_decision,
            "decision_source": self.decision_source,
            "flags": self.flags,
            "reasons": self.reasons,
            "anomaly_score": self.anomaly_score,
            "adjusted_score": self.adjusted_score,
            "adjusted_score_unclipped": self.adjusted_score_unclipped,
            "boost_total": self.boost_total,
            "final_score": self.final_score,
            "final_score_unclipped": self.final_score_unclipped,
        }


class RuleEngine(RuleEvaluator):
    """Applies the repository's rules (or a request-time rule set) with learned thresholds."""

    def __init__(
        self,
        repository: RuleRepository,
        params: dict[str, Any],
        cooldown_store: CooldownStore | None = None,
    ) -> None:
        self.repository = repository
        self.params = dict(params)
        # online cooldown state (batch runs always start from a fresh store)
        self.cooldown_store = cooldown_store if cooldown_store is not None else CooldownStore()

    @property
    def settings(self) -> RuleSettings:
        """Current engine settings (re-read by repository.reload())."""
        return self.repository.settings

    def active_rules(self, rules: list[Rule] | None = None) -> list[Rule]:
        """Enabled rules of the given set (default: the loaded set)."""
        return [r for r in (self.repository.rules if rules is None else rules) if r.enabled]

    def required_inputs(self, rules: list[Rule]) -> list[str]:
        """Input columns a record must carry for these rules (conditions + message fields)."""
        names: set[str] = set()
        for rule in rules:
            names |= condition_features(rule.condition) | template_fields(rule.message)
        names -= set(self.params) | set(SCORE_COLUMNS)
        needed: set[str] = set()
        for name in names:
            needed |= set(DERIVED_DEPS.get(name, [name]))
        if any(r.cooldown for r in rules):
            needed |= set(self.settings.cooldown_columns)
        return sorted(needed)

    # ---- shared core (batch and online) ----
    def hit_matrix(self, df: pd.DataFrame, rules: list[Rule]) -> pd.DataFrame:
        """Boolean frame (rows of df x rule ids): did the rule's condition hold?"""
        data = {r.id: evaluate_condition(r.condition, df, self.params) for r in rules}
        return pd.DataFrame(data, index=df.index, columns=[r.id for r in rules], dtype=bool)

    def apply_cooldowns(
        self, frame: pd.DataFrame, hits: pd.DataFrame, rules: list[Rule], store: CooldownStore
    ) -> tuple[pd.DataFrame, list[list[str]]]:
        """Drop hits of cooldown rules whose entity already fired within the window.

        Returns the kept hits and, per row, the ids removed by a cooldown. Same code for batch
        (fresh store, rows in time order) and online (engine's store).
        """
        cooled: list[list[str]] = [[] for _ in range(len(hits))]
        cool_rules = [r for r in rules if r.cooldown is not None]
        if not cool_rules:
            return hits, cooled
        hits = hits.copy()
        times = frame[self.settings.time_column].to_numpy("float64")
        keys = cooldown_keys(frame, self.settings.entity_columns)
        for rule in cool_rules:
            raw = hits[rule.id].to_numpy(dtype=bool)
            kept = apply_cooldown(
                raw, times, keys, rule.cooldown.window_seconds, store.for_rule(rule.id)
            )
            hits[rule.id] = kept
            for i in np.flatnonzero(raw & ~kept):
                cooled[i].append(rule.id)
        return hits, cooled

    def score_review_threshold(self) -> float | None:
        """Score-based review threshold, or None when disabled."""
        s = self.settings
        if not s.score_review_enabled:
            return None
        return float(resolve_value(s.score_review_threshold, self.params))

    def decide(
        self, hits: pd.DataFrame, rules: list[Rule], adjusted_unclipped: pd.Series
    ) -> pd.DataFrame:
        """Conflict resolution per row, boosts, final scores and decisions.

        Resolution depends only on which rules fired, so it is computed once per distinct
        hit pattern and mapped back to the rows.
        """
        s = self.settings
        by_id = {r.id: r for r in rules}
        ids = list(hits.columns)
        arr = hits.to_numpy(dtype=bool)
        if arr.shape[1] == 0:  # no active rule: one all-false column keeps np.unique simple
            arr = np.zeros((len(hits), 1), dtype=bool)
        patterns, inverse = np.unique(arr, axis=0, return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        resolved: list[Resolution] = [
            resolve([by_id[ids[j]] for j in np.flatnonzero(p)], s.boost_min, s.boost_max)
            for p in patterns
        ]
        res = [resolved[i] for i in inverse]
        out = pd.DataFrame(index=hits.index)
        out["triggered_rules"] = [list(r.triggered) for r in res]
        out["applied_rules"] = [list(r.applied) for r in res]
        out["suppressed_rules"] = [[rid for rid, _ in r.suppressed] for r in res]
        out["suppressed_reasons"] = [[why for _, why in r.suppressed] for r in res]
        out["boost_raw"] = np.array([r.boost_raw for r in res], dtype="float64")
        out["boost"] = np.array([r.boost for r in res], dtype="float64")
        base = adjusted_unclipped.loc[hits.index].astype("float64")
        out[FINAL_UNCLIPPED] = base + out["boost"]
        out[FINAL] = out[FINAL_UNCLIPPED].clip(s.clip_min, s.clip_max)

        decision = pd.Series([r.decision for r in res], index=hits.index, dtype=object)
        source = pd.Series([r.winner for r in res], index=hits.index, dtype=object)
        undecided = decision.isna()
        threshold = self.score_review_threshold()
        if threshold is not None:
            # the score is compared before any rule boost; an allow rule cannot override a
            # score-threshold review (resolver rule 4), so its effect is undone on those rows
            over = base >= threshold
            allow_lost = (decision == "allow") & over
            applied, lost_ids = list(out["applied_rules"]), list(out["suppressed_rules"])
            reasons = list(out["suppressed_reasons"])
            for i in np.flatnonzero(allow_lost.to_numpy()):
                lost_ids[i] = [*lost_ids[i], *applied[i]]
                reasons[i] = [*reasons[i], *[ALLOW_VS_SCORE_REASON] * len(applied[i])]
                applied[i] = []
            out["applied_rules"], out["suppressed_rules"] = applied, lost_ids
            out["suppressed_reasons"] = reasons
            out.loc[allow_lost, ["boost_raw", "boost"]] = 0.0
            out[FINAL_UNCLIPPED] = base + out["boost"]
            out[FINAL] = out[FINAL_UNCLIPPED].clip(s.clip_min, s.clip_max)
            by_score = (undecided | allow_lost) & over
            decision[by_score], source[by_score] = "review", "score"
            undecided &= ~by_score
        decision[undecided], source[undecided] = s.default_decision, "default"
        out["final_decision"] = decision
        out["decision_source"] = source
        return out

    # ---- batch ----
    def evaluate_batch(
        self, df: pd.DataFrame, scores: pd.DataFrame, rules: list[Rule] | None = None
    ) -> pd.DataFrame:
        """Evaluate many rows. scores holds anomaly_score, adjusted_score, adjusted_score_unclipped.

        Returns scores + per-rule hit columns + resolution/decision columns, indexed like df.
        """
        rules = self.active_rules(rules)
        frame = add_derived(df.join(scores[SCORE_COLUMNS]), self.settings.daily_avg_min_days)
        hits = self.hit_matrix(frame, rules)
        hits, cooled = self.apply_cooldowns(frame, hits, rules, CooldownStore())
        decided = self.decide(hits, rules, frame[ADJUSTED_UNCLIPPED])
        out = frame[SCORE_COLUMNS].join(decided)
        out["cooldown_rules"] = cooled
        for rid in hits.columns:
            out[f"{HIT_PREFIX}{rid}"] = hits[rid].astype("int8")
        return out

    # ---- online ----
    def evaluate(
        self,
        record: dict[str, Any],
        anomaly_score: float,
        rules: list[Rule] | list[dict[str, Any]] | str | None = None,
        update_state: bool = True,
    ) -> RuleEngineResult:
        """Evaluate one record.

        anomaly_score: the Step 6 adjusted score the rules boost (adjusted_score_unclipped).
        The record may carry `anomaly_score` (Step 5) and `adjusted_score` (clipped) for display.
        rules: optional request-time rule set (Rule objects, dicts or JSON text); it is validated
        with the same schema and used only for this call.
        update_state: record this call's fires in the cooldown store (False = read only).
        Cooldown rules need the record's TransactionDT and entity columns.
        """
        if rules is not None and not all(isinstance(r, Rule) for r in rules):
            rules = self.repository.parse(rules)  # type: ignore[arg-type]
        active = self.active_rules(rules)  # type: ignore[arg-type]
        missing = [c for c in self.required_inputs(active) if c not in record]
        if missing:
            raise KeyError(f"record is missing rule inputs: {missing}")
        s = self.settings
        row = {k: v for k, v in record.items() if k not in SCORE_COLUMNS}
        scores = {
            ANOMALY: record.get(ANOMALY),
            ADJUSTED: record.get(ADJUSTED, min(max(anomaly_score, s.clip_min), s.clip_max)),
            ADJUSTED_UNCLIPPED: float(anomaly_score),
        }
        frame = add_derived(pd.DataFrame([{**row, **scores}]), s.daily_avg_min_days)
        hits = self.hit_matrix(frame, active)
        store = self.cooldown_store if update_state else self.cooldown_store.copy()
        hits, cooled = self.apply_cooldowns(frame, hits, active, store)
        decided = self.decide(hits, active, frame[ADJUSTED_UNCLIPPED]).iloc[0]
        return self._result(frame.iloc[0].to_dict(), decided, active, cooled[0])

    def _result(
        self,
        values: dict[str, Any],
        decided: pd.Series,
        rules: list[Rule],
        cooled: list[str] | None = None,
    ) -> RuleEngineResult:
        by_id = {r.id: r for r in rules}
        fill = {**values, **self.params}
        applied = list(decided["applied_rules"])
        reasons = [render_message(by_id[rid].message, fill) for rid in applied]
        source = str(decided["decision_source"])
        final_unclipped = float(decided[FINAL_UNCLIPPED])
        threshold = self.score_review_threshold()
        if source == "score":
            reasons.append(
                f"Karar kuralı tetiklenmedi; skor {final_unclipped:.3f} inceleme eşiğinin "
                f"({threshold:.3f}) üzerinde."
            )
        elif source == "default":
            limit = f" (inceleme eşiği {threshold:.3f})" if threshold is not None else ""
            reasons.append(f"Karar kuralı tetiklenmedi; skor {final_unclipped:.3f}{limit}.")
        if decided["boost_raw"] != decided["boost"]:
            reasons.append(
                f"Kural artışları toplamı {decided['boost_raw']:+.2f}, sınır "
                f"[{self.settings.boost_min:+.2f}, {self.settings.boost_max:+.2f}] ile "
                f"{decided['boost']:+.2f} yapıldı."
            )
        triggered = [by_id[rid] for rid in decided["triggered_rules"]]
        suppressed = [
            {"id": rid, "reason": why, "message": render_message(by_id[rid].message, fill)}
            for rid, why in zip(
                decided["suppressed_rules"], decided["suppressed_reasons"], strict=True
            )
        ]
        for rid in cooled or []:
            window = by_id[rid].cooldown.window_seconds  # type: ignore[union-attr]
            suppressed.append(
                {
                    "id": rid,
                    "reason": COOLDOWN_REASON.format(window=window),
                    "message": render_message(by_id[rid].message, fill),
                }
            )
        anomaly = to_python(values.get(ANOMALY))
        return RuleEngineResult(
            action=str(decided["final_decision"]),
            final_decision=str(decided["final_decision"]),
            decision_source=source,
            final_score=float(decided[FINAL]),
            final_score_unclipped=final_unclipped,
            triggered_rules=[r.id for r in triggered],
            applied_rules=applied,
            triggered_details=[
                {
                    "id": r.id,
                    "name": r.name,
                    "priority": r.priority,
                    "severity": r.severity,
                    "decision": r.action.decision,
                    "risk_boost": r.action.risk_boost,
                }
                for r in triggered
            ],
            suppressed_rules=suppressed,
            flags=[by_id[rid].action.flag for rid in applied],
            reasons=reasons,
            explanations=[
                Explanation(source=f"rule:{rid}", message=text)
                for rid, text in zip(applied, reasons, strict=False)
            ],
            anomaly_score=None if anomaly is None else float(anomaly),
            adjusted_score=float(values[ADJUSTED]),
            adjusted_score_unclipped=float(values[ADJUSTED_UNCLIPPED]),
            boost_total=float(decided["boost"]),
        )
