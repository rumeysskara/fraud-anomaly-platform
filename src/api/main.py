"""FastAPI application factory. `uvicorn src.api.main:app` starts the service.

All services come from the DI container (src/container.py); there is no global state here. Models
and histories are loaded once at startup from artifacts/ (nothing is trained at request time).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from src.api.errors import register_error_handlers
from src.api.routers import explain, health, rag, rules, score
from src.container import Container, create_container

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
ROUTER_MODULES = [score, explain, rules, rag, health]


def create_app(container: Container | None = None) -> FastAPI:
    """Build the app. Tests pass a container with overridden providers."""
    container = container or create_container()
    container.wire(modules=ROUTER_MODULES)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _warm_up(container)
        yield

    app = FastAPI(
        title="Fraud & Anomaly Detection Platform",
        version="0.1.0",
        description=(
            "Scores raw IEEE-CIS style transactions with layered anomaly detection, context "
            "adjustment and a configurable rule engine. /score never calls the LLM; /explain "
            "returns deterministic facts plus an optional local-LLM narrative."
        ),
        lifespan=lifespan,
    )
    app.container = container  # type: ignore[attr-defined]
    register_error_handlers(app)

    @app.middleware("http")
    async def request_id_and_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        logger.info(
            "%s %s -> %s in %.0f ms (request %s)",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            request.state.request_id,
        )
        return response

    for module in ROUTER_MODULES:
        app.include_router(module.router)
    return app


def _warm_up(container: Container) -> None:
    """Load models and history now so the first request is fast; failures only log.

    The Ollama models are warmed in a background thread (K-50), so startup does not wait for them.
    """
    try:
        summary = container.online_scorer().state_summary()
        logger.info("online state loaded: %s", summary)
    except Exception as exc:  # noqa: BLE001 - /health reports it, endpoints answer 503
        logger.error("could not load model artifacts: %s", exc)
    container.model_warmer().start()


app = create_app()
