"""API settings. Values come from configs/api.yaml when it exists; the defaults below apply
otherwise (the file only overrides, it is not required)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from src.agents.config import AgentSettings
from src.core.config import CONFIG_DIR, load_yaml

API_CONFIG_FILE = "api.yaml"


class LLMSettings(BaseModel):
    """Deadlines for calls that wait for the local LLM.

    timeout_seconds is the total budget of one /explain or /rag/query request. /explain runs the
    planner and then the explainer one after the other, so the budget is split statically between
    them (Step 8-10 review, Ö5); their sum may not exceed the total.
    """

    timeout_seconds: float = Field(default=60.0, gt=0)
    planner_timeout_seconds: float = Field(default=10.0, gt=0)
    explainer_timeout_seconds: float = Field(default=50.0, gt=0)

    @model_validator(mode="after")
    def _split_fits_total(self) -> LLMSettings:
        if self.planner_timeout_seconds + self.explainer_timeout_seconds > self.timeout_seconds:
            raise ValueError(
                "planner_timeout_seconds + explainer_timeout_seconds must not exceed "
                "timeout_seconds"
            )
        return self


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


class WarmupSettings(BaseModel):
    """Background warm-up of the Ollama models at startup (K-50)."""

    enabled: bool = True
    embedding_text: str = "warm-up"
    llm_prompt: str = "Yalnızca 'tamam' yaz."


class ApiSettings(BaseModel):
    """Whole configs/api.yaml."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    online: OnlineSettings = Field(default_factory=OnlineSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)
    rag: RagApiSettings = Field(default_factory=RagApiSettings)
    warmup: WarmupSettings = Field(default_factory=WarmupSettings)


def load_api_settings(config_dir: Path = CONFIG_DIR) -> ApiSettings:
    """Load configs/api.yaml (defaults when the file is absent)."""
    if not (config_dir / API_CONFIG_FILE).exists():
        return ApiSettings()
    return ApiSettings.model_validate(load_yaml(API_CONFIG_FILE, config_dir))


def agent_settings_for_api(agents: AgentSettings, api: ApiSettings) -> AgentSettings:
    """Copy of the agent settings whose LLM deadlines are capped by the API budget split.

    configs/agents.yaml keeps the long batch/demo limits (explainer 240 s); the API caps the
    planner and the explainer with their share of `llm.timeout_seconds` (default 10 s + 50 s), so
    /explain answers within the total and returns the facts when that is not enough.
    """
    llm = api.llm
    settings = agents.model_copy(deep=True)
    settings.explainer.timeout_seconds = min(
        settings.explainer.timeout_seconds, llm.explainer_timeout_seconds
    )
    settings.planner.timeout_seconds = min(
        settings.planner.timeout_seconds, llm.planner_timeout_seconds
    )
    return settings
