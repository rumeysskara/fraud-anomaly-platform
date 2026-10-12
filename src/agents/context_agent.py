"""ContextAgent: Step 6 context-aware adjustment and the C rules that were applied."""

from __future__ import annotations

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.messages import (
    ANOMALY,
    CONTEXT,
    INTENT_ADJUST,
    INTENT_SCORE,
    AdjustReply,
    AdjustRequest,
    BusMessage,
    ScoreReply,
    ScoreRequest,
)
from src.context.derive import LAYER_SCORE_SUFFIX
from src.context.engine import UNCLIPPED
from src.core.interfaces import ContextAdjuster


class ContextAgent(Agent):
    """Adjusts the anomaly score with context. Asks the AnomalyAgent when it has no score."""

    def __init__(self, bus: MessageBus, adjuster: ContextAdjuster) -> None:
        super().__init__(CONTEXT, bus)
        self.adjuster = adjuster
        self.on(INTENT_ADJUST, self._adjust)

    def _adjust(self, message: BusMessage) -> AdjustReply:
        request = AdjustRequest.model_validate(message.payload)
        score, layers = request.anomaly_score, request.layer_scores
        record, built = request.record, None
        if score is None or layers is None:  # delegation: the score comes from the anomaly agent
            ask = ScoreRequest(record=record, transaction=request.transaction)
            scored = ScoreReply.model_validate(self.delegate(ANOMALY, INTENT_SCORE, ask, message))
            score, layers = scored.anomaly_score, scored.layer_scores
            built = scored.record
            record = record if record is not None else built
        if record is None:
            raise ValueError("adjust got scores but no record")
        # the engine reads <layer>_score columns next to the features
        record = {**record, **{f"{k}{LAYER_SCORE_SUFFIX}": v for k, v in layers.items()}}
        result = self.adjuster.adjust_one(record, score)
        unclipped = result.adjusted_score
        for item in result.explanations:
            if UNCLIPPED in item.details:
                unclipped = float(item.details[UNCLIPPED])
        return AdjustReply(
            anomaly_score=score,
            layer_scores=layers,
            adjusted_score=result.adjusted_score,
            adjusted_score_unclipped=unclipped,
            applied_rules=result.applied_rules,
            explanations=[e.model_dump() for e in result.explanations],
            record=built,
        )
