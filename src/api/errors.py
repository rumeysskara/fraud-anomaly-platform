"""Consistent JSON errors: {"error": {"code", "message", "details", "request_id"}}."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.rag.errors import RagError
from src.rules.repository import RuleValidationError

logger = logging.getLogger(__name__)

RULE_LABEL = re.compile(r"^rule ([^:]+):")


class ServiceUnavailable(Exception):
    """A required artifact (model, index) is not available; maps to HTTP 503."""


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request, status: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    """Build the error envelope."""
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": _request_id(request),
        }
    }
    return JSONResponse(status_code=status, content=body)


def _field_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": ".".join(str(p) for p in e["loc"] if p != "body"),
            "message": str(e["msg"]),
            "type": str(e["type"]),
        }
        for e in exc.errors()
    ]


BRANCH_TAGS = ("AllNode", "AnyNode", "NotNode")


def _is_branch(segment: Any) -> bool:
    """True for the union branch names pydantic puts into the error location of a condition."""
    return isinstance(segment, str) and (segment in BRANCH_TAGS or segment.startswith("function-"))


def _drop_wrong_branches(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A condition is a union (all / any / not / single clause); pydantic reports the errors of
    every branch. Keep only the branch the user meant: one with no error on its own level (a
    branch that fits the keys given); if none fits, the one with the fewest errors."""
    wrong: set[int] = set()
    groups: dict[tuple[Any, ...], dict[Any, list[dict[str, Any]]]] = {}
    for e in errors:
        for i, part in enumerate(e["loc"]):
            if _is_branch(part):
                groups.setdefault(tuple(e["loc"][:i]), {}).setdefault(part, []).append(e)
    for prefix, branches in groups.items():
        if len(branches) < 2:
            continue
        depth = len(prefix) + 2  # own level: <prefix>.<branch>.<field>
        own = {b: any(len(e["loc"]) == depth for e in items) for b, items in branches.items()}
        keep = [b for b in branches if not own[b]] or [
            min(branches, key=lambda b: len(branches[b]))
        ]
        for b, items in branches.items():
            if b not in keep:
                wrong.update(id(e) for e in items)
    return [e for e in errors if id(e) not in wrong]


def _rule_errors(exc: RuleValidationError) -> list[dict[str, str]]:
    """Readable list from a RuleValidationError (pydantic details when the schema failed)."""
    match = RULE_LABEL.match(str(exc))
    rule = match.group(1) if match else None
    cause = exc.__cause__
    if isinstance(cause, ValidationError):
        return [
            {
                "rule": rule or "",
                "field": ".".join(str(p) for p in e["loc"] if not _is_branch(p)),
                "message": str(e["msg"]),
            }
            for e in _drop_wrong_branches(list(cause.errors()))
        ]
    return [{"rule": rule or "", "field": "", "message": str(exc)}]


def register_error_handlers(app: FastAPI) -> None:
    """Attach the handlers: 422 (input and rule sets), 503 (missing artifacts), 500 (rest)."""

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            request, 422, "validation_error", "Request body is invalid.", _field_errors(exc)
        )

    @app.exception_handler(RuleValidationError)
    async def _rules(request: Request, exc: RuleValidationError) -> JSONResponse:
        return error_response(
            request, 422, "invalid_rule_set", "The rule set is invalid.", _rule_errors(exc)
        )

    @app.exception_handler(json.JSONDecodeError)
    async def _json(request: Request, exc: json.JSONDecodeError) -> JSONResponse:
        return error_response(request, 422, "invalid_json", f"Invalid JSON: {exc}")

    @app.exception_handler(ServiceUnavailable)
    async def _unavailable(request: Request, exc: ServiceUnavailable) -> JSONResponse:
        return error_response(request, 503, "service_unavailable", str(exc))

    @app.exception_handler(FileNotFoundError)
    async def _missing_file(request: Request, exc: FileNotFoundError) -> JSONResponse:
        logger.error("missing artifact: %s", exc)
        return error_response(
            request, 503, "artifact_missing", f"A required artifact is missing: {exc}"
        )

    @app.exception_handler(RagError)
    async def _rag(request: Request, exc: RagError) -> JSONResponse:
        return error_response(request, 503, "rag_unavailable", f"{type(exc).__name__}: {exc}")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error (request %s)", _request_id(request))
        return error_response(request, 500, "internal_error", "Internal server error.")
