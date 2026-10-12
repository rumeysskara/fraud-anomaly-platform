"""POST /explain: facts (code) + narrative (LLM, optional) + agent trace. Writes no state."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.api.schemas import ExplainRequest, ExplainResponse
from src.api.services import ExplainService
from src.container import Container

router = APIRouter(tags=["explain"])


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Explain a decision: deterministic facts plus an optional LLM narrative",
)
@inject
def explain(
    body: ExplainRequest,
    service: ExplainService = Depends(Provide[Container.explain_service]),  # noqa: B008
) -> ExplainResponse:
    """Runs the Step 9 agent flow.

    `facts` are computed by code and are the only authority for numbers. `narrative` is LLM text
    labelled as supporting information; it is null when the LLM is down or too slow
    (`llm_status` says why). The entity history and cooldown state are not changed.
    """
    return service.explain(body.transaction.model_dump(), body.question)
