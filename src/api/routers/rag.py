"""POST /rag/query: question -> answer + sources from the knowledge base."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.api.schemas import RagQueryRequest, RagQueryResponse
from src.api.services import RagQueryService
from src.container import Container

router = APIRouter(tags=["rag"])


@router.post(
    "/rag/query",
    response_model=RagQueryResponse,
    summary="Ask the knowledge base (retrieval + local LLM)",
)
@inject
def rag_query(
    body: RagQueryRequest,
    service: RagQueryService = Depends(Provide[Container.rag_query_service]),  # noqa: B008
) -> RagQueryResponse:
    """Answer with sources. If Ollama is down, `answer` is null and `llm_status` explains it."""
    rule_ids = body.filters.rule_ids if body.filters else []
    return service.query(body.question, body.k, rule_ids)
