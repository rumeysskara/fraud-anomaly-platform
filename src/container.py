"""DI container. Later steps only ADD providers; never remove existing ones."""

from __future__ import annotations

from dependency_injector import containers, providers

from src.context.factory import load_engine
from src.core.config import ARTIFACTS_DIR, CONFIG_DIR
from src.features.pipeline import FeaturePipeline
from src.rules.factory import load_rule_engine
from src.rules.repository import RuleRepository
from src.scoring.service import ScoringService


class Container(containers.DeclarativeContainer):
    """Single application container (providers are added by later steps)."""

    config = providers.Configuration()

    # Step 3: fitted feature pipeline + entity store (loaded lazily; the API never trains).
    feature_pipeline = providers.Singleton(
        FeaturePipeline.load,
        ARTIFACTS_DIR / "feature_pipeline.joblib",
        ARTIFACTS_DIR / "entity_profiles.parquet",
    )

    # Step 4-5: fitted anomaly layers + weights + normalization tables (loaded, never trained).
    scoring_service = providers.Singleton(ScoringService.load, ARTIFACTS_DIR / "detectors")

    # Step 6: context adjuster (configs/context.yaml + fit-learned params + Step 5 weights/table).
    context_adjuster = providers.Singleton(load_engine, ARTIFACTS_DIR / "detectors")

    # Step 7: rule repository (configs/rules.yaml + rules_extra.json, reload()) and rule engine
    # (thresholds learned on the fit set, stored in rules.yaml `learned:`; never fitted here).
    rule_repository = providers.Singleton(RuleRepository, CONFIG_DIR / "rules.yaml")
    rule_engine = providers.Singleton(load_rule_engine, rule_repository)


def create_container() -> Container:
    """Create the container and load configs/settings.yaml into it."""
    container = Container()
    container.config.from_yaml(str(CONFIG_DIR / "settings.yaml"))
    return container
