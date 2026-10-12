"""Typed access to configs/agents.yaml (pydantic v2)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from src.core.config import CONFIG_DIR, load_yaml


class RoleConfig(BaseModel):
    """One agent role: description and the intents it accepts."""

    description: str
    intents: list[str]


class StepConfig(BaseModel):
    """One workflow step."""

    agent: str
    intent: str

    @property
    def key(self) -> str:
        """'agent:intent' form used in plans and traces."""
        return f"{self.agent}:{self.intent}"


class WorkflowConfig(BaseModel):
    """Default plan and the mandatory step."""

    default_plan: list[StepConfig]
    required_step: StepConfig


class BusConfig(BaseModel):
    """Message bus limits."""

    max_depth: int = 6


class PlannerConfig(BaseModel):
    """LLM planner settings."""

    enabled: bool = True
    timeout_seconds: float = 60.0
    max_steps: int = 6
    prompt: str


class RuleAgentConfig(BaseModel):
    """RuleAgent settings."""

    update_state: bool = False


class ExplainerConfig(BaseModel):
    """ExplainerAgent settings."""

    timeout_seconds: float = 240.0
    label: str = "destek bilgisi"
    default_question: str


class AgentSettings(BaseModel):
    """Whole configs/agents.yaml."""

    roles: dict[str, RoleConfig]
    workflow: WorkflowConfig
    bus: BusConfig = Field(default_factory=BusConfig)
    planner: PlannerConfig
    rule: RuleAgentConfig = Field(default_factory=RuleAgentConfig)
    explainer: ExplainerConfig

    @model_validator(mode="after")
    def _check_steps(self) -> AgentSettings:
        steps = [*self.workflow.default_plan, self.workflow.required_step]
        for step in steps:
            role = self.roles.get(step.agent)
            if role is None or step.intent not in role.intents:
                raise ValueError(f"workflow step {step.key} is not an allowed agent/intent")
        if self.workflow.required_step.key not in [s.key for s in self.workflow.default_plan]:
            raise ValueError("default_plan must contain the required step")
        return self

    def allowed_steps(self) -> list[str]:
        """All 'agent:intent' pairs in canonical (config) order."""
        return [f"{name}:{i}" for name, role in self.roles.items() for i in role.intents]


def load_agent_settings(config_dir: Path = CONFIG_DIR) -> AgentSettings:
    """Load and validate configs/agents.yaml."""
    return AgentSettings.model_validate(load_yaml("agents.yaml", config_dir))
