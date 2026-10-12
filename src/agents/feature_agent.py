"""FeatureAgent: Step 3 record building for a raw transaction (FeaturePipeline.transform_one)."""

from __future__ import annotations

from collections.abc import Callable

from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.messages import (
    FEATURE,
    INTENT_FEATURIZE,
    BusMessage,
    FeaturizeReply,
    FeaturizeRequest,
)
from src.core.interfaces import RecordSource


class FeatureAgent(Agent):
    """Builds the scoring record of one raw transaction. Single responsibility: features.

    No feature logic lives here: the injected RecordSource (the API's OnlineScorer) runs the
    same code as /score (FeaturePipeline.transform_one + raw fields), read-only. It is not a plan
    step; the AnomalyAgent asks it when it gets a transaction instead of a record.
    `records` is a provider so the feature pipeline is loaded only when this agent runs.
    """

    def __init__(self, bus: MessageBus, records: Callable[[], RecordSource]) -> None:
        super().__init__(FEATURE, bus)
        self.records = records
        self.on(INTENT_FEATURIZE, self._featurize)

    def _featurize(self, message: BusMessage) -> FeaturizeReply:
        request = FeaturizeRequest.model_validate(message.payload)
        return FeaturizeReply(record=self.records().record_for(request.transaction))
