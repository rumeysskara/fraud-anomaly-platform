"""Planner: deterministic default plan, optional LLM plan validated against an allow-list.

The LLM only chooses which allowed agents run and in which order. Any problem (LLM down, timeout,
invalid JSON, unknown agent/intent, wrong order, missing rule step) means the default plan is used
and the reason is returned so the coordinator can write `plan_fallback` to the trace.
"""

from __future__ import annotations

import json
import logging
import re
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agents.config import AgentSettings
from src.agents.errors import AgentError
from src.agents.messages import PlanInfo
from src.agents.timeouts import call_with_timeout
from src.core.interfaces import LLMClient

logger = logging.getLogger(__name__)


class PlanStep(BaseModel):
    """One step of an LLM plan. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")
    agent: str
    intent: str

    @property
    def key(self) -> str:
        """'agent:intent' form."""
        return f"{self.agent}:{self.intent}"


class LLMPlan(BaseModel):
    """JSON the LLM must return: {"steps": [{"agent": ..., "intent": ...}]}."""

    model_config = ConfigDict(extra="forbid")
    steps: list[PlanStep] = Field(min_length=1)


class Planner:
    """Builds the plan for a request."""

    def __init__(self, llm: LLMClient | None, settings: AgentSettings) -> None:
        self.llm = llm
        self.settings = settings

    def default_plan(self) -> list[str]:
        """The configured deterministic plan (score -> context -> rules -> explain)."""
        return [s.key for s in self.settings.workflow.default_plan]

    def plan(self, question: str | None) -> PlanInfo:
        """Default plan without a question; an LLM plan (validated) with one."""
        default = self.default_plan()
        if not question:
            return PlanInfo(source="default", steps=default)
        started = time.perf_counter()
        try:
            steps = self._llm_steps(question)
        except (AgentError, ValueError) as exc:
            logger.warning("plan_fallback: %s", exc)
            return PlanInfo(
                source="fallback",
                steps=default,
                fallback_reason=str(exc),
                duration_ms=_ms(started),
            )
        return PlanInfo(source="llm", steps=steps, duration_ms=_ms(started))

    def _llm_steps(self, question: str) -> list[str]:
        cfg = self.settings.planner
        if not cfg.enabled:
            raise AgentError("planner disabled")
        if self.llm is None:
            raise AgentError("no planner LLM")
        catalog = "\n".join(
            f"- {name}:{intent} - {role.description}"
            for name, role in self.settings.roles.items()
            for intent in role.intents
        )
        system = cfg.prompt.format(catalog=catalog)
        llm = self.llm
        try:
            text = call_with_timeout(lambda: llm.generate(question, system), cfg.timeout_seconds)
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001 - any LLM failure means fallback
            raise AgentError(f"planner LLM failed: {type(exc).__name__}: {exc}") from exc
        return self.validate(text)

    def validate(self, text: str) -> list[str]:
        """Parse and check an LLM answer; return 'agent:intent' keys or raise ValueError."""
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("plan is not JSON")
        try:
            plan = LLMPlan.model_validate(json.loads(match.group(0)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"invalid plan JSON: {exc.__class__.__name__}") from exc
        keys = [s.key for s in plan.steps]
        allowed = self.settings.allowed_steps()
        unknown = [k for k in keys if k not in allowed]
        if unknown:
            raise ValueError(f"disallowed agent/intent in plan: {unknown}")
        if len(keys) > self.settings.planner.max_steps or len(set(keys)) != len(keys):
            raise ValueError("plan has too many or repeated steps")
        if keys != sorted(keys, key=allowed.index):
            raise ValueError("plan steps are not in dependency order")
        if self.settings.workflow.required_step.key not in keys:
            raise ValueError("plan does not contain the rule step")
        return keys


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
