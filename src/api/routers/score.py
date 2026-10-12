"""POST /score: raw transaction -> scores, context rules, rules and the final decision."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.api.mappers import to_score_response
from src.api.online import OnlineScorer
from src.api.schemas import ScoreResponse, TransactionIn
from src.container import Container

router = APIRouter(tags=["score"])


@router.post(
    "/score",
    response_model=ScoreResponse,
    summary="Score one transaction (no LLM; updates the online history once per TransactionID)",
)
@inject
def score(
    body: TransactionIn,  # type: ignore[valid-type]
    scorer: OnlineScorer = Depends(Provide[Container.online_scorer]),  # noqa: B008
) -> ScoreResponse:
    """Layer scores, context adjustment, rules and decision. Never calls the LLM.

    The first call for a TransactionID appends the transaction to the in-memory entity history and
    the cooldown state; repeating the id returns the same result (`duplicate=true`).
    """
    outcome, duplicate, latency = scorer.score(body.model_dump())  # type: ignore[attr-defined]
    return to_score_response(outcome, duplicate, latency)
