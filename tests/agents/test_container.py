"""Container wiring: agents are built from overridable services; no label in the agent layer."""

from __future__ import annotations

from pathlib import Path

from dependency_injector import providers

from src.agents.coordinator import CoordinatorAgent
from src.agents.messages import AnalystRequest
from src.container import Container
from tests.agents.conftest import (
    RECORD,
    FakeAdjuster,
    FakeEngine,
    FakePlannerLLM,
    FakeRAG,
    FakeScoring,
)

ROOT = Path(__file__).resolve().parents[2]
LABEL = "is" + "Fraud"  # split so this file does not match itself


def test_coordinator_uses_overridden_services() -> None:
    container = Container()
    container.scoring_service.override(providers.Object(FakeScoring()))
    container.context_adjuster.override(providers.Object(FakeAdjuster()))
    container.rule_engine.override(providers.Object(FakeEngine("allow", [])))
    container.rag_service.override(providers.Object(FakeRAG()))
    container.planner_llm.override(providers.Object(FakePlannerLLM()))
    coordinator = container.coordinator()
    assert isinstance(coordinator, CoordinatorAgent)
    assert coordinator is container.coordinator()  # Singleton
    assert set(container.message_bus().agents) == {
        "feature",
        "anomaly",
        "context",
        "rule",
        "explainer",
        "coordinator",
    }
    response = coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.decision == "allow" and response.status == "ok"


def test_label_name_absent_from_agent_files() -> None:
    files = [
        *(ROOT / "src" / "agents").rglob("*.py"),
        ROOT / "configs" / "agents.yaml",
        ROOT / "scripts" / "run_agents_demo.py",
    ]
    offenders = [str(f) for f in files if f.is_file() and LABEL in f.read_text(encoding="utf-8")]
    assert offenders == []


def test_agents_do_not_import_each_other() -> None:
    """Mediator rule: agent modules only know the bus, messages and services."""
    names = ["anomaly_agent", "context_agent", "rule_agent", "explainer_agent", "feature_agent"]
    for name in names:
        text = (ROOT / "src" / "agents" / f"{name}.py").read_text(encoding="utf-8")
        for other in names:
            assert f"src.agents.{other}" not in text
