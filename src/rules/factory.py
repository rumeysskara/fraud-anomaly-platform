"""Factory: build the RuleEngine from the repository and saved thresholds (no fitting)."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from src.rules.cooldown import CooldownStore
from src.rules.engine import RuleEngine
from src.rules.params import load_params
from src.rules.repository import RuleRepository


def load_rule_engine(
    repository: RuleRepository,
    cooldown_store: CooldownStore,
    sample: bool = False,
    sample_dir: Path | None = None,
) -> RuleEngine:
    """Rule engine with learned thresholds (rules.yaml `learned:`) + external params.

    The same loader is given to the engine so that engine.reload() re-reads the thresholds.
    """
    loader = partial(load_params, sample=sample, sample_dir=sample_dir)
    return RuleEngine(repository, loader(repository.settings), cooldown_store, loader)
