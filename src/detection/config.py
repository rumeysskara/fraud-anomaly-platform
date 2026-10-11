"""Loaders for configs/anomaly.yaml and configs/weights.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.config import CONFIG_DIR, load_settings, load_yaml

WEIGHT_TOLERANCE = 1e-6


def load_anomaly_config(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Load configs/anomaly.yaml."""
    return load_yaml("anomaly.yaml", config_dir)


def load_weights(config_dir: Path = CONFIG_DIR) -> dict[str, float]:
    """Load layer weights from configs/weights.yaml and check they sum to 1."""
    weights = {k: float(v) for k, v in load_yaml("weights.yaml", config_dir)["weights"].items()}
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(f"layer weights must sum to 1, got {total}")
    return weights


def seed() -> int:
    """Project seed from configs/settings.yaml."""
    return int(load_settings()["seed"])
