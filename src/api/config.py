"""API settings. Values come from configs/api.yaml when it exists; the defaults below apply
otherwise (the file only overrides, it is not required)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from src.agents.config import AgentSettings
from src.core.config import CONFIG_DIR, load_yaml

API_CONFIG_FILE = "api.yaml"


class LLMSettings(BaseModel):
    """Deadline for every call that may wait for the local LLM (/explain, /rag/query)."""

    timeout_seconds: float = Field(default=60.0, gt=0)


class OnlineSettings(BaseModel):
    """Size of the in-memory caches that make /score idempotent per TransactionID."""

    result_cache_size: int = Field(default=5000, ge=1)  # small score results
    record_cache_size: int = Field(default=256, ge=1)  # full feature records (about 30 KB each)


class HealthSettings(BaseModel):
    """/health probe limits."""

    ollama_timeout_seconds: float = Field(default=2.0, gt=0)


class RagApiSettings(BaseModel):
    """Limits of POST /rag/query."""

    max_k: int = Field(default=10, ge=1)
    max_question_chars: int = Field(default=1000, ge=1)


class ApiSettings(BaseModel):
    """Whole configs/api.yaml."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    online: OnlineSettings = Field(default_factory=OnlineSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)
    rag: RagApiSettings = Field(default_factory=RagApiSettings)


def load_api_settings(config_dir: Path = CONFIG_DIR) -> ApiSettings:
    """Load configs/api.yaml (defaults when the file is absent)."""
    if not (config_dir / API_CONFIG_FILE).exists():
        return ApiSettings()
    return ApiSettings.model_validate(load_yaml(API_CONFIG_FILE, config_dir))


def agent_settings_for_api(agents: AgentSettings, api: ApiSettings) -> AgentSettings:
    """Copy of the agent settings whose LLM deadlines are capped by the API deadline.

    configs/agents.yaml keeps the long batch/demo limits (explainer 240 s); the API answers
    within `llm.timeout_seconds` (default 60 s) and returns the facts when that is not enough.
    """
    limit = api.llm.timeout_seconds
    settings = agents.model_copy(deep=True)
    settings.explainer.timeout_seconds = min(settings.explainer.timeout_seconds, limit)
    settings.planner.timeout_seconds = min(settings.planner.timeout_seconds, limit)
    return settings
