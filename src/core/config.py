"""Settings loader and path constants."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "configs"
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
REPORTS_DIR = ROOT_DIR / "reports"


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Load configs/<name> (e.g. 'settings.yaml') into a dict."""
    with open(config_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Load configs/settings.yaml."""
    return load_yaml("settings.yaml", config_dir)


def get_sample_n() -> int | None:
    """Read SAMPLE_N env var; None means full data."""
    value = os.environ.get("SAMPLE_N", "").strip()
    return int(value) if value else None


def set_seed(seed: int | None = None) -> None:
    """Seed python, numpy using settings.yaml `seed` when seed is None.

    sklearn and faiss take the seed as a parameter (read it from settings too).
    """
    import random

    import numpy as np

    seed = load_settings()["seed"] if seed is None else seed
    random.seed(seed)
    np.random.seed(seed)
