"""AnomalyAgent: Step 4-5 layer scores and the normalized aggregate (ScoringService)."""

from __future__ import annotations

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.messages import (
    ANOMALY,
    FEATURE,
    INTENT_FEATURIZE,
    INTENT_SCORE,
    BusMessage,
    FeaturizeReply,
    FeaturizeRequest,
    ScoreReply,
    ScoreRequest,
)
from src.scoring.service import ScoringService


class AnomalyAgent(Agent):
    """Scores one record with the fitted layers. Single responsibility: the anomaly score.

    Given a raw transaction instead of a record, it asks the FeatureAgent for the record
    (delegation) and returns that record with the scores so the later steps can use it.
    """

    def __init__(self, bus: MessageBus, scoring: ScoringService) -> None:
        super().__init__(ANOMALY, bus)
        self.scoring = scoring
        self.on(INTENT_SCORE, self._score)

    def _score(self, message: BusMessage) -> ScoreReply:
        request = ScoreRequest.model_validate(message.payload)
        record, built = request.record, None
        if record is None:  # delegation: the feature agent builds the record
            ask = FeaturizeRequest(transaction=request.transaction or {})
            reply = FeaturizeReply.model_validate(
                self.delegate(FEATURE, INTENT_FEATURIZE, ask, message)
            )
            record = built = reply.record
        result = self.scoring.score_one(record)
        return ScoreReply(
            anomaly_score=result.score,
            raw_score=result.raw_score,
            layer_scores=result.layer_scores,
            explanations=[e.model_dump() for e in result.explanations],
            record=built,
        )
