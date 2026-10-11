"""DI container. Later steps only ADD providers; never remove existing ones."""

from __future__ import annotations

from dependency_injector import containers, providers

from src.core.config import ARTIFACTS_DIR, CONFIG_DIR
from src.features.pipeline import FeaturePipeline


class Container(containers.DeclarativeContainer):
    """Single application container (providers are added by later steps)."""

    config = providers.Configuration()

    # Step 3: fitted feature pipeline + entity store (loaded lazily; the API never trains).
    feature_pipeline = providers.Singleton(
        FeaturePipeline.load,
        ARTIFACTS_DIR / "feature_pipeline.joblib",
        ARTIFACTS_DIR / "entity_profiles.parquet",
    )


def create_container() -> Container:
    """Create the container and load configs/settings.yaml into it."""
    container = Container()
    container.config.from_yaml(str(CONFIG_DIR / "settings.yaml"))
    return container
