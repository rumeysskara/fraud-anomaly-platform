"""RuleEngine: evaluates configurable rules on top of the Step 6 adjusted score.

Batch (parquet) and online (one record, API) use the same functions: add_derived ->
hit_matrix -> decide. A single record is a one-row DataFrame.
"""

from __future__ import annotations

from collections.abc import Callable
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
from src.rules.resolver import (
    ALLOW_VS_SCORE_REASON,
    Resolution,
    resolve,
    resolve_score_over_allow,
)
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
    """Applies the repository's rules (or a request-time rule set) with learned thresholds.

    The cooldown store is injected (container Singleton); batch runs never touch it.
    params_loader (optional) re-reads the thresholds on reload().
    """

    def __init__(
        self,
        repository: RuleRepository,
        params: dict[str, Any],
        cooldown_store: CooldownStore,
        params_loader: Callable[[RuleSettings], dict[str, Any]] | None = None,
    ) -> None:
        self.repository = repository
        self.params = dict(params)
        self.cooldown_store = cooldown_store
        self._params_loader = params_loader

    @property
    def settings(self) -> RuleSettings:
        """Current engine settings (re-read by reload())."""
        return self.repository.settings

    def reload(self) -> list[Rule]:
        """Re-read rule files, settings and (with a params_loader) the learned thresholds."""
        rules = self.repository.reload()
        if self._params_loader is not None:
            self.params = dict(self._params_loader(self.settings))
        return rules

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
            needed |= {*self.settings.cooldown_columns, self.settings.id_column}
        return sorted(needed)

    # ---- shared core (batch and online) ----
    def hit_matrix(self, df: pd.DataFrame, rules: list[Rule]) -> pd.DataFrame:
        """Boolean frame (rows of df x rule ids): did the rule's condition hold?"""
        data = {r.id: evaluate_condition(r.condition, df, self.params) for r in rules}
        return pd.DataFrame(data, index=df.index, columns=[r.id for r in rules], dtype=bool)

    def apply_cooldowns(
        self,
        frame: pd.DataFrame,
        hits: pd.DataFrame,
        rules: list[Rule],
        ids: np.ndarray,
        states: dict[str, dict[str, float]],
    ) -> tuple[pd.DataFrame, list[list[str]]]:
        """Drop hits of cooldown rules whose entity already fired within the window.

        ids: TransactionIDs (tie-break of equal times). states: rule id -> {entity key: last
        kept fire time}, updated in place (batch: empty; online: built from the store).
        Returns the kept hits and, per row, the ids removed by a cooldown.
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
            window = rule.cooldown.window_seconds  # type: ignore[union-attr]
            kept = apply_cooldown(raw, times, keys, window, states.setdefault(rule.id, {}), ids)
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

        The resolution depends only on which rules fired and on whether the score (before any
        boost) reaches the review threshold, so it is computed once per distinct (hit pattern,
        over threshold) pair and mapped back to the rows. When the score reaches the threshold
        an allow rule is void (resolver rule 4) and the rules are resolved again without it.
        """
        s = self.settings
        by_id = {r.id: r for r in rules}
        ids = list(hits.columns)
        arr = hits.to_numpy(dtype=bool)
        if arr.shape[1] == 0:  # no active rule: one all-false column keeps np.unique simple
            arr = np.zeros((len(hits), 1), dtype=bool)
        patterns, inverse = np.unique(arr, axis=0, return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        base = adjusted_unclipped.loc[hits.index].astype("float64")
        threshold = self.score_review_threshold()
        over = (
            (base >= threshold).to_numpy() if threshold is not None else np.zeros(len(base), bool)
        )
        combo = inverse * 2 + over.astype(np.int64)
        cache: dict[int, Resolution] = {}
        for c in np.unique(combo):
            triggered = [by_id[ids[j]] for j in np.flatnonzero(patterns[c // 2])]
            res = resolve(triggered, s.boost_min, s.boost_max)
            if c % 2 == 1 and res.decision == "allow":
                res = resolve_score_over_allow(triggered, s.boost_min, s.boost_max)
            cache[int(c)] = res
        res_rows = [cache[int(c)] for c in combo]

        out = pd.DataFrame(index=hits.index)
        out["triggered_rules"] = [list(r.triggered) for r in res_rows]
        out["applied_rules"] = [list(r.applied) for r in res_rows]
        out["suppressed_rules"] = [[rid for rid, _ in r.suppressed] for r in res_rows]
        out["suppressed_reasons"] = [[why for _, why in r.suppressed] for r in res_rows]
        out["boost_raw"] = np.array([r.boost_raw for r in res_rows], dtype="float64")
        out["boost"] = np.array([r.boost for r in res_rows], dtype="float64")
        out[FINAL_UNCLIPPED] = base + out["boost"]
        out[FINAL] = out[FINAL_UNCLIPPED].clip(s.clip_min, s.clip_max)

        decision = pd.Series([r.decision for r in res_rows], index=hits.index, dtype=object)
        source = pd.Series([r.winner for r in res_rows], index=hits.index, dtype=object)
        undecided = decision.isna().to_numpy()
        by_score = undecided & over
        decision[by_score], source[by_score] = "review", "score"
        default = undecided & ~over
        decision[default], source[default] = s.default_decision, "default"
        out["final_decision"] = decision
        out["decision_source"] = source
        return out

    # ---- batch ----
    def evaluate_batch(
        self, df: pd.DataFrame, scores: pd.DataFrame, rules: list[Rule] | None = None
    ) -> pd.DataFrame:
        """Evaluate many rows (index = TransactionID). scores holds anomaly_score,
        adjusted_score, adjusted_score_unclipped. Cooldowns start from an empty state and use
        (TransactionDT, TransactionID) order; the online store is not touched.

        Returns scores + per-rule hit columns + resolution/decision columns, indexed like df.
        """
        rules = self.active_rules(rules)
        frame = add_derived(df.join(scores[SCORE_COLUMNS]), self.settings.daily_avg_min_days)
        hits = self.hit_matrix(frame, rules)
        hits, cooled = self.apply_cooldowns(frame, hits, rules, frame.index.to_numpy(), {})
        decided = self.decide(hits, rules, frame[ADJUSTED_UNCLIPPED])
        out = frame[SCORE_COLUMNS].join(decided)
        out["cooldown_rules"] = cooled
        for rid in hits.columns:
            out[f"{HIT_PREFIX}{rid}"] = hits[rid].astype("int8")
        return out

    # ---- online ----
    def _online_states(
        self, frame: pd.DataFrame, rules: list[Rule], tid: int
    ) -> dict[str, dict[str, float]]:
        """Cooldown state just before this transaction (fires strictly before (time, id))."""
        states: dict[str, dict[str, float]] = {}
        cool_rules = [r for r in rules if r.cooldown is not None]
        if not cool_rules:
            return states
        time = float(frame[self.settings.time_column].iloc[0])
        key = cooldown_keys(frame, self.settings.entity_columns)[0]
        for rule in cool_rules:
            last = self.cooldown_store.last_fire_before(rule.id, key, time, tid)
            states[rule.id] = {} if last is None else {key: last}
        return states

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
        with the same schema and used only for this call. A request-time set READS the cooldown
        state but never writes it.
        update_state: for the loaded rule set, record this transaction's fires in the store.
        The store is updated at most once per TransactionID, so evaluating the same transaction
        again returns the same result. Cooldown rules need TransactionID, TransactionDT and the
        entity columns in the record.
        """
        request_time = rules is not None
        if request_time and not all(isinstance(r, Rule) for r in rules):  # type: ignore[union-attr]
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
        tid = int(record[s.id_column]) if s.id_column in record else -1
        states = self._online_states(frame, active, tid)
        hits, cooled = self.apply_cooldowns(frame, hits, active, np.array([tid]), states)
        if update_state and not request_time and states:
            self._record_fires(frame, hits, active, tid)
        decided = self.decide(hits, active, frame[ADJUSTED_UNCLIPPED]).iloc[0]
        return self._result(frame.iloc[0].to_dict(), decided, active, cooled[0])

    def _record_fires(
        self, frame: pd.DataFrame, hits: pd.DataFrame, rules: list[Rule], tid: int
    ) -> None:
        """Write this transaction's kept cooldown fires to the store (once per id)."""
        cool_rules = [r for r in rules if r.cooldown is not None]
        key = cooldown_keys(frame, self.settings.entity_columns)[0]
        fires = [(r.id, key) for r in cool_rules if bool(hits[r.id].iloc[0])]
        window = max(r.cooldown.window_seconds for r in cool_rules)  # type: ignore[union-attr]
        time = float(frame[self.settings.time_column].iloc[0])
        self.cooldown_store.record(tid, time, fires, window)

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
        if ALLOW_VS_SCORE_REASON in list(decided["suppressed_reasons"]):
            reasons.append(
                "Skor inceleme eşiğinin üzerinde; allow kuralı yok sayıldı ve kurallar onsuz "
                "yeniden çözüldü."
            )
        source = str(decided["decision_source"])
        final_unclipped = float(decided[FINAL_UNCLIPPED])
        threshold = self.score_review_threshold()
        if source == "score":
            head = (
                "Block/review kuralı tetiklenmedi"
                if len(decided["triggered_rules"])
                else "Karar kuralı tetiklenmedi"
            )
            reasons.append(
                f"{head}; skor {final_unclipped:.3f} inceleme eşiğinin ({threshold:.3f}) üzerinde."
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
