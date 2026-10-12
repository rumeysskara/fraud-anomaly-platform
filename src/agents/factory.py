"""AgentFactory (Factory pattern): builds the agents from injected services and registers them."""

from __future__ import annotations

from src.agents.anomaly_agent import AnomalyAgent
from src.agents.base import Agent
from src.agents.bus import MessageBus
from src.agents.config import AgentSettings
from src.agents.context_agent import ContextAgent
from src.agents.coordinator import CoordinatorAgent
from src.agents.explainer_agent import ExplainerAgent
from src.agents.messages import ANOMALY, CONTEXT, COORDINATOR, EXPLAINER, RULE
from src.agents.planner import Planner
from src.agents.rule_agent import RuleAgent
from src.core.interfaces import ContextAdjuster
from src.rag.config import LLMConfig
from src.rag.llm import OllamaLLMClient
from src.rag.service import RAGService
from src.rules.engine import RuleEngine
from src.scoring.service import ScoringService


class AgentFactory:
    """Creates agents by role name. Services are injected; nothing is built from globals."""

    def __init__(
        self,
        bus: MessageBus,
        settings: AgentSettings,
        scoring: ScoringService,
        adjuster: ContextAdjuster,
        rule_engine: RuleEngine,
        rag: RAGService,
        planner: Planner,
    ) -> None:
        self.bus = bus
        self.settings = settings
        self.scoring = scoring
        self.adjuster = adjuster
        self.rule_engine = rule_engine
        self.rag = rag
        self.planner = planner

    def create(self, role: str) -> Agent:
        """Build one agent (not registered)."""
        if role == ANOMALY:
            return AnomalyAgent(self.bus, self.scoring)
        if role == CONTEXT:
            return ContextAgent(self.bus, self.adjuster)
        if role == RULE:
            return RuleAgent(self.bus, self.rule_engine, self.settings.rule.update_state)
        if role == EXPLAINER:
            return ExplainerAgent(self.bus, self.rag, self.settings.explainer)
        if role == COORDINATOR:
            return CoordinatorAgent(self.bus, self.planner)
        raise ValueError(f"unknown agent role '{role}'")

    def create_system(self) -> CoordinatorAgent:
        """Build every agent, register them on the bus and return the coordinator."""
        coordinator: CoordinatorAgent | None = None
        for role in (ANOMALY, CONTEXT, RULE, EXPLAINER, COORDINATOR):
            agent = self.create(role)
            self.bus.register(agent)
            if isinstance(agent, CoordinatorAgent):
                coordinator = agent
        assert coordinator is not None
        return coordinator


def build_planner_llm(llm_config: LLMConfig, settings: AgentSettings) -> OllamaLLMClient:
    """Planner LLM: the RAG model with the planner timeout and temperature 0."""
    config = llm_config.model_copy(
        update={"timeout_seconds": settings.planner.timeout_seconds, "temperature": 0.0}
    )
    return OllamaLLMClient(config)


def create_coordinator(factory: AgentFactory) -> CoordinatorAgent:
    """Container entry point: the ready-to-use coordinator."""
    return factory.create_system()
