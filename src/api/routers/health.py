"""GET /health: model artifacts, FAISS index and Ollama."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.api.health import HealthService
from src.api.schemas import HealthResponse
from src.container import Container

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Dependency status")
@inject
def health(
    service: HealthService = Depends(Provide[Container.health_service]),  # noqa: B008
) -> HealthResponse:
    """Always 200; `status` is ok, degraded (LLM side not ready) or down (no models)."""
    return service.check()
