"""Factory: build the RuleEngine from the repository and saved thresholds (no fitting)."""

from __future__ import annotations

from pathlib import Path

from src.rules.engine import RuleEngine
from src.rules.params import load_params
from src.rules.repository import RuleRepository


def load_rule_engine(
    repository: RuleRepository, sample: bool = False, sample_dir: Path | None = None
) -> RuleEngine:
    """Rule engine with learned thresholds (rules.yaml `learned:`) + external params."""
    return RuleEngine(repository, load_params(repository.settings, sample, sample_dir))
