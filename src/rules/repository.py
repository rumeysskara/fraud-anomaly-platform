"""RuleRepository: loads and validates rules from YAML and JSON files (Repository pattern)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.core.config import CONFIG_DIR, load_yaml
from src.core.interfaces import RuleStore
from src.rules.derive import DERIVED_COLUMNS
from src.rules.schema import Rule, condition_features, condition_params, template_fields

logger = logging.getLogger(__name__)

RULES_FILE = "rules.yaml"


class RuleValidationError(ValueError):
    """A rule set failed schema or name validation."""


@dataclass
class RuleSettings:
    """Engine settings: everything in configs/rules.yaml except the rule list."""

    files: list[str]
    boost_min: float
    boost_max: float
    clip_min: float
    clip_max: float
    score_review_enabled: bool
    score_review_threshold: Any
    default_decision: str
    daily_avg_min_days: float
    inputs: dict[str, list[str]]
    learned_params: dict[str, dict[str, Any]]
    external_params: dict[str, dict[str, Any]]
    time_column: str = "TransactionDT"
    entity_columns: list[str] = field(default_factory=list)
    learned: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_dir: Path = CONFIG_DIR) -> RuleSettings:
        """Build from the parsed rules.yaml (entity key columns come from the entity config)."""
        review = data["decision"]["score_review"]
        cool = data["cooldown"]
        return cls(
            files=list(data["files"]["rules"]),
            boost_min=float(data["boost"]["min_total"]),
            boost_max=float(data["boost"]["max_total"]),
            clip_min=float(data["score_clip"]["min"]),
            clip_max=float(data["score_clip"]["max"]),
            score_review_enabled=bool(review["enabled"]),
            score_review_threshold=review["threshold"],
            default_decision=str(data["decision"]["default"]),
            daily_avg_min_days=float(data["derived"]["daily_avg_min_days"]),
            inputs={k: list(v) for k, v in data["inputs"].items()},
            learned_params=dict(data.get("learned_params") or {}),
            external_params=dict(data.get("external_params") or {}),
            time_column=str(cool["time_column"]),
            entity_columns=list(load_yaml(cool["entity_config"], config_dir)["entity"]["columns"]),
            learned=dict(data.get("learned") or {}),
        )

    @property
    def input_columns(self) -> list[str]:
        """Every input column (features, raw, history, scores)."""
        return [c for cols in self.inputs.values() for c in cols]

    @property
    def known_features(self) -> set[str]:
        """Names a condition may reference: inputs + derived columns."""
        return set(self.input_columns) | set(DERIVED_COLUMNS)

    @property
    def cooldown_columns(self) -> list[str]:
        """Columns a record needs when a rule has a cooldown (time + entity key)."""
        return [self.time_column, *self.entity_columns]

    @property
    def param_names(self) -> set[str]:
        """Names a {param: name} reference may use."""
        return set(self.learned_params) | set(self.external_params)


def _read_rule_items(path: Path) -> list[dict[str, Any]]:
    """Raw rule dicts from a YAML or JSON file (top-level key `rules`)."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    return list((data or {}).get("rules") or [])


class RuleRepository(RuleStore):
    """Loads rules.yaml settings and every rule file listed in it; reload() re-reads them."""

    def __init__(self, config_path: Path = CONFIG_DIR / RULES_FILE) -> None:
        self.config_path = Path(config_path)
        self.settings: RuleSettings
        self._rules: list[Rule] = []
        self.reload()

    @property
    def rules(self) -> list[Rule]:
        """All loaded rules (enabled and disabled), in file order."""
        return list(self._rules)

    def reload(self) -> list[Rule]:
        """Re-read the settings and rule files; an invalid file keeps the previous set."""
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        settings = RuleSettings.from_dict(data, self.config_path.parent)
        items: list[dict[str, Any]] = []
        for name in settings.files:
            items += _read_rule_items(self.config_path.parent / name)
        rules = validate_rules(items, settings)
        self.settings, self._rules = settings, rules
        logger.info("loaded %d rules from %s", len(rules), settings.files)
        return self.rules

    def parse(self, payload: str | dict[str, Any] | list[dict[str, Any]]) -> list[Rule]:
        """Validate a rule set sent with a request (JSON text, {"rules": [...]} or a list)."""
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            payload = payload.get("rules", [])
        return validate_rules(list(payload), self.settings)


def validate_rules(items: list[dict[str, Any]], settings: RuleSettings) -> list[Rule]:
    """Schema-validate rule dicts and check ids, feature, param and template names."""
    rules: list[Rule] = []
    for i, item in enumerate(items):
        try:
            rules.append(Rule.model_validate(item))
        except ValidationError as exc:
            label = item.get("id", f"#{i}") if isinstance(item, dict) else f"#{i}"
            raise RuleValidationError(f"rule {label}: {exc}") from exc
    ids = [r.id for r in rules]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        raise RuleValidationError(f"duplicate rule ids: {duplicates}")
    known, params = settings.known_features, settings.param_names
    for rule in rules:
        unknown = condition_features(rule.condition) - known
        if unknown:
            raise RuleValidationError(f"rule {rule.id}: unknown feature(s) {sorted(unknown)}")
        missing = condition_params(rule.condition) - params
        if missing:
            raise RuleValidationError(f"rule {rule.id}: unknown param(s) {sorted(missing)}")
        bad = template_fields(rule.message) - known - params
        if bad:
            raise RuleValidationError(f"rule {rule.id}: unknown message field(s) {sorted(bad)}")
    return rules
