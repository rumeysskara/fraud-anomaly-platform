"""DI wiring of the API, label-free API code and layer direction."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from dependency_injector import providers
from pydantic import ValidationError

from src.agents.config import load_agent_settings
from src.api.artifacts import resolve_artifact_set
from src.api.config import ApiSettings, LLMSettings, agent_settings_for_api, load_api_settings
from src.container import Container
from tests.api.conftest import World

ROOT = Path(__file__).resolve().parents[2]
LABEL = "is" + "Fraud"  # split so this file does not match itself


def test_api_providers_are_injected_not_built_in_services() -> None:
    world = World()
    container = Container()
    container.online_scorer.override(providers.Object(world.scorer))
    container.rag_service.override(providers.Object(world.rag))
    container.api_coordinator.override(providers.Object(world.coordinator))
    container.api_settings.override(providers.Object(world.api_settings))
    assert container.explain_service().scorer is world.scorer
    assert container.explain_service().coordinator is world.coordinator
    assert container.rag_query_service().rag is world.rag
    assert container.explain_service() is container.explain_service()  # Singleton


def test_api_agents_use_a_separate_bus_and_the_api_deadline() -> None:
    container = Container()
    api = container.api_settings()
    assert api.llm.timeout_seconds == 60.0
    capped = container.api_agents_settings()
    assert capped.planner.timeout_seconds == 10.0 and capped.explainer.timeout_seconds == 50.0
    assert container.agents_settings().explainer.timeout_seconds == 240.0  # Step 9 unchanged
    assert container.api_message_bus() is not container.message_bus()


def test_agent_settings_are_capped_but_never_raised() -> None:
    agents = load_agent_settings()
    big = LLMSettings(
        timeout_seconds=900.0, planner_timeout_seconds=300.0, explainer_timeout_seconds=500.0
    )
    raised = agent_settings_for_api(agents, ApiSettings(llm=big))
    assert raised.explainer.timeout_seconds == 240.0 and raised.planner.timeout_seconds == 60.0
    small = LLMSettings(
        timeout_seconds=6.0, planner_timeout_seconds=1.0, explainer_timeout_seconds=5.0
    )
    capped = agent_settings_for_api(agents, ApiSettings(llm=small))
    assert capped.explainer.timeout_seconds == 5.0 and capped.planner.timeout_seconds == 1.0
    assert agents.explainer.timeout_seconds == 240.0  # the original object is untouched


def test_planner_plus_explainer_may_not_exceed_the_total() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(
            timeout_seconds=60.0, planner_timeout_seconds=20.0, explainer_timeout_seconds=50.0
        )


def test_artifact_set_follows_sample_n() -> None:
    full, sample = resolve_artifact_set(None), resolve_artifact_set(50000)
    assert not full.sample and full.feature_pipeline.name == "feature_pipeline.joblib"
    assert full.detectors_dir.name == "detectors"
    assert sample.sample and sample.feature_pipeline.name == "feature_pipeline_sample.joblib"
    assert sample.entity_profiles.name == "entity_profiles_sample.parquet"
    assert sample.detectors_dir.name == "sample" and sample.context_params_dir.name == "sample"


def test_api_settings_default_when_file_is_missing(tmp_path: Path) -> None:
    assert load_api_settings(tmp_path).llm.timeout_seconds == 60.0


def test_no_label_in_api_code_or_examples() -> None:
    files = [*(ROOT / "src" / "api").rglob("*.py"), *(ROOT / "examples").rglob("*.json")]
    assert files
    assert [str(f) for f in files if LABEL.lower() in f.read_text().lower()] == []


def test_lower_layers_do_not_import_the_api() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+src\.api", re.MULTILINE)
    offenders = []
    for layer in ("agents", "rag", "rules", "context", "scoring", "detection", "features", "data"):
        for path in (ROOT / "src" / layer).rglob("*.py"):
            if pattern.search(path.read_text()):
                offenders.append(str(path))
    assert offenders == []


def test_health_index_path_is_repo_relative(world: World) -> None:
    from src.api.health import HealthService
    from src.rag.config import load_rag_settings

    service = HealthService(lambda: world.scorer, load_rag_settings(), world.api_settings, None)  # type: ignore[arg-type]
    assert not service.index().detail["path"].startswith("/")
