"""Access to configs/profiling.yaml (single source of profiling thresholds)."""

from __future__ import annotations

from typing import Any

from src.core.config import load_yaml


def profiling_config(section: str | None = None) -> dict[str, Any]:
    """Return configs/profiling.yaml, or one top-level section of it."""
    cfg = load_yaml("profiling.yaml")
    return cfg[section] if section else cfg


def entity_definition() -> dict[str, Any]:
    """Return the chosen entity proxy block (`entity:`) of configs/entity.yaml (single source)."""
    return load_yaml("entity.yaml")["entity"]
