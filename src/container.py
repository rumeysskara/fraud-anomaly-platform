"""DI container. Later steps only ADD providers; never remove existing ones."""

from __future__ import annotations

from dependency_injector import containers, providers

from src.core.config import CONFIG_DIR


class Container(containers.DeclarativeContainer):
    """Single application container (providers are added by later steps)."""

    config = providers.Configuration()


def create_container() -> Container:
    """Create the container and load configs/settings.yaml into it."""
    container = Container()
    container.config.from_yaml(str(CONFIG_DIR / "settings.yaml"))
    return container
