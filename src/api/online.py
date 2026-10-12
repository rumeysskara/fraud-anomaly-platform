"""Online scoring: one raw transaction -> record -> layer scores -> context -> rules.

This is the single place where a raw API payload becomes the record the Step 4-7 services expect.
Batch and online use the same services and the same feature code (FeaturePipeline.transform_one,
ScoringService.score_one, ContextAdjustEngine.adjust_one, RuleEngine.evaluate); nothing is trained
here. The entity history (Step 3 EntityStore, Step 4 hour store) is loaded from artifacts/ at start
and `score()` appends each new transaction to it. State lives in memory, in one process.

No LLM is touched in this module.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.api.config import ApiSettings
from src.context.derive import EMAIL_KNOWN, LAYER_SCORE_SUFFIX
from src.context.engine import UNCLIPPED
from src.context.inputs import RAW_SOURCE_COLUMNS
from src.core.interfaces import ContextAdjuster, RecordSource
from src.detection.aux import AUX_SOURCE_COLUMNS, build_aux
from src.features.pipeline import FeaturePipeline
from src.features.utils import NA_KEY, amount_array, entity_keys, get_col, value_keys
from src.rules.engine import RuleEngine, RuleEngineResult
from src.scoring.service import ScoringService

logger = logging.getLogger(__name__)

OUT_OF_ORDER = "out_of_order_transaction"
NUMERIC_KEYS = ("card1", "addr1")  # the entity key is built from numeric values (as in batch)


@dataclass(frozen=True)
class ScoreOutcome:
    """Everything one evaluation produced (scores, context entries, rule result)."""

    transaction_id: int
    anomaly_score: float
    raw_anomaly_score: float
    layer_scores: dict[str, float]
    adjusted_score: float
    adjusted_score_unclipped: float
    context_rules: list[dict[str, Any]]
    rule: RuleEngineResult
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryKeys:
    """The keys and values one transaction contributes to the entity history."""

    entity: str
    card: str
    device: str
    email: str
    dt: int
    amount: float


class _LRU:
    """Small ordered dict with a size limit (oldest entries are dropped)."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._items: OrderedDict[int, Any] = OrderedDict()

    def get(self, key: int) -> Any | None:
        """Return the entry (and mark it recent) or None."""
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def put(self, key: int, value: Any) -> None:
        """Store an entry; drop the oldest ones above the limit."""
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.size:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)


class OnlineScorer(RecordSource):
    """Scores single transactions with the fitted services and keeps the online history.

    - `score(txn)`: the /score path. Updates entity history, hour history and the cooldown store
      once per TransactionID; scoring the same id again returns the first result unchanged.
    - `analyze(txn, rules)`: read-only (no state is written); used by /explain and /rules/evaluate.
    A lock serializes calls: history is read and written as one step, and a transaction takes
    well under a second, so one process serves roughly 10 transactions per second.
    """

    def __init__(
        self,
        pipeline: FeaturePipeline,
        scoring: ScoringService,
        adjuster: ContextAdjuster,
        engine: RuleEngine,
        settings: ApiSettings,
    ) -> None:
        self.pipeline = pipeline
        self.scoring = scoring
        self.adjuster = adjuster
        self.engine = engine
        self._lock = threading.RLock()
        self._results = _LRU(settings.online.result_cache_size)
        self._records = _LRU(settings.online.record_cache_size)

    # ---- record assembly (no state change) ----------------------------------------------------

    def _raw_columns(self) -> list[str]:
        """Raw fields copied into the record next to the features (rules and context read them)."""
        s = self.engine.settings
        return list(
            dict.fromkeys(
                [*RAW_SOURCE_COLUMNS, *AUX_SOURCE_COLUMNS, *s.inputs["raw"], *s.cooldown_columns]
            )
        )

    def history_keys(self, txn: dict[str, Any]) -> HistoryKeys:
        """Entity/card/device/e-mail keys of a payload, built like the batch history inputs."""
        frame = self._key_frame(txn)
        h = self.pipeline.config["history"]
        return HistoryKeys(
            entity=str(entity_keys(frame, self.pipeline.entity_columns).iloc[0]),
            card=str(value_keys(get_col(frame, "card1")).iloc[0]),
            device=str(value_keys(get_col(frame, h["device_column"])).iloc[0]),
            email=str(value_keys(get_col(frame, h["email_column"])).iloc[0]),
            dt=int(txn["TransactionDT"]),
            amount=float(amount_array(frame)[0]),
        )

    @staticmethod
    def _key_frame(txn: dict[str, Any]) -> pd.DataFrame:
        """One-row frame with the columns the key functions read (numeric dtypes like batch)."""
        row: dict[str, Any] = {k: txn.get(k) for k in ("DeviceInfo", "P_emaildomain")}
        for key in NUMERIC_KEYS:
            row[key] = pd.to_numeric(pd.Series([txn.get(key)]), errors="coerce").iloc[0]
        row["TransactionAmt"] = float(txn["TransactionAmt"])
        return pd.DataFrame([row])

    def build_record(self, txn: dict[str, Any]) -> dict[str, Any]:
        """Features + raw fields + aux columns + the past-only e-mail flag for one payload."""
        feats = self.pipeline.transform_one(txn, update=False)
        record: dict[str, Any] = dict(feats)
        record.update({c: _clean(txn.get(c)) for c in self._raw_columns()})
        keys = self.history_keys(txn)
        aux = build_aux(self._key_frame(txn)).iloc[0]
        record.update({k: _clean(v) for k, v in aux.items()})
        store = self.pipeline.store
        seen = store.entities.get(keys.entity) if store is not None else None
        record[EMAIL_KNOWN] = int(
            seen is not None and keys.email != NA_KEY and keys.email in seen.emails
        )
        record["TransactionID"] = int(txn["TransactionID"])
        return record

    # ---- evaluation ---------------------------------------------------------------------------

    def evaluate(
        self, record: dict[str, Any], update_state: bool, rules: Any = None
    ) -> ScoreOutcome:
        """Scores -> context -> rules for a ready record (same steps as the agents)."""
        scored = self.scoring.score_one(record)
        layers = scored.layer_scores
        ctx_record = {**record, **{f"{k}{LAYER_SCORE_SUFFIX}": v for k, v in layers.items()}}
        adjusted = self.adjuster.adjust_one(ctx_record, scored.score)
        unclipped = adjusted.adjusted_score
        entries: list[dict[str, Any]] = []
        for item in adjusted.explanations:
            if UNCLIPPED in item.details:
                unclipped = float(item.details[UNCLIPPED])
            if "factor" in item.details and "id" in item.details:
                entries.append(item.details)
        rule_record = {
            **record,
            "anomaly_score": scored.score,
            "adjusted_score": adjusted.adjusted_score,
        }
        result = self.engine.evaluate(
            rule_record, unclipped, rules=rules, update_state=update_state
        )
        warnings = []
        gap = record.get("time_since_last_txn")
        if gap is not None and gap < 0 and gap != -1:
            warnings.append(OUT_OF_ORDER)  # older than the entity's newest known transaction
        return ScoreOutcome(
            transaction_id=int(record["TransactionID"]),
            anomaly_score=scored.score,
            raw_anomaly_score=scored.raw_score,
            layer_scores=dict(layers),
            adjusted_score=adjusted.adjusted_score,
            adjusted_score_unclipped=unclipped,
            context_rules=entries,
            rule=result,
            warnings=warnings,
        )

    def score(self, txn: dict[str, Any]) -> tuple[ScoreOutcome, bool, float]:
        """The /score path. Returns (outcome, duplicate, latency_ms).

        The first call for a TransactionID evaluates with update_state=True (cooldown fires are
        recorded once, K-27) and appends the transaction to the entity and hour history. A repeated
        id returns the first outcome and changes nothing.
        """
        started = time.perf_counter()
        tid = int(txn["TransactionID"])
        with self._lock:
            known = self._results.get(tid)
            if known is not None:
                return known, True, _ms(started)
            record = self.build_record(txn)
            outcome = self.evaluate(record, update_state=True)
            self._commit(txn, record)
            self._results.put(tid, outcome)
            self._records.put(tid, record)
        return outcome, False, _ms(started)

    def analyze(
        self, txn: dict[str, Any], rules: Any = None
    ) -> tuple[dict[str, Any], ScoreOutcome]:
        """Read-only evaluation: (record, outcome). Writes no history and no cooldown state.

        A transaction that /score already handled reuses its recorded features (the history
        before it), so explaining it later gives the same numbers.
        """
        with self._lock:
            record = self.record_for(txn)
            return record, self.evaluate(record, update_state=False, rules=rules)

    def record_for(self, txn: dict[str, Any]) -> dict[str, Any]:
        """Record of a transaction without writing state (FeatureAgent and `analyze` use it).

        A transaction that /score already handled returns its recorded features (the history
        before it); any other transaction is built with `build_record` (update=False).
        """
        tid = int(txn["TransactionID"])
        with self._lock:
            return self._records.get(tid) or self.build_record(txn)

    def _commit(self, txn: dict[str, Any], record: dict[str, Any]) -> None:
        """Append the transaction to the entity history and the temporal hour history."""
        self.append_history(txn, record.get("hour"))

    def append_history(self, txn: dict[str, Any], hour: int | None) -> None:
        """Add one transaction to the entity history and (given its hour) the hour history.

        Used by /score after scoring. Also usable to fast-forward the history to a point in time
        without scoring (consistency checks); the caller keeps the time order.
        """
        keys = self.history_keys(txn)
        if self.pipeline.store is not None:
            self.pipeline.store.update(
                keys.entity, keys.card, keys.device, keys.email, keys.dt, keys.amount
            )
        temporal = self.scoring.detectors.get("temporal")
        hour_store = getattr(temporal, "store", None)
        if hour_store is not None and hour is not None:
            hours = int(getattr(temporal, "hours", 24))
            row = hour_store.counts.get(keys.entity)
            if row is not None and not row.flags.writeable:
                # arrays restored from artifacts can be read-only views (HourStore.update would
                # fail); copy this entity's row before writing to it
                hour_store.counts[keys.entity] = row.copy()
            hour_store.update(keys.entity, int(hour) % hours)

    def parse_rules(self, payload: Any) -> list[Any]:
        """Validate a request-supplied rule set (raises RuleValidationError)."""
        return self.engine.repository.parse(payload)

    # ---- facts about the loaded state (for /health and /explain) --------------------------------

    def thresholds(self) -> dict[str, float | None]:
        """Decision thresholds from the rule configuration."""
        s = self.engine.settings
        return {
            "score_review": self.engine.score_review_threshold(),
            "boost_min": s.boost_min,
            "boost_max": s.boost_max,
        }

    def state_summary(self) -> dict[str, Any]:
        """Sizes of the loaded online state."""
        store = self.pipeline.store
        temporal = self.scoring.detectors.get("temporal")
        hour_store = getattr(temporal, "store", None)
        return {
            "layers": list(self.scoring.detectors),
            "entities_in_history": len(store.entities) if store is not None else 0,
            "entities_in_hour_history": len(hour_store.counts) if hour_store is not None else 0,
            "rules_loaded": len(self.engine.repository.rules),
        }


def _clean(value: Any) -> Any:
    """NaN/NaT -> None; numpy scalars -> Python scalars."""
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, str):
        value = value.item()
    return None if isinstance(value, float) and value != value else value


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
