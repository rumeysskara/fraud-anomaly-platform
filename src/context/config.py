"""Load and validate configs/context.yaml into small typed objects."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from src.core.config import CONFIG_DIR, load_yaml

RULE_TYPES = ("multiplicative", "layer_weight")


@dataclass(frozen=True)
class RuleSpec:
    """One context rule as written in the config."""

    id: str
    group: str
    name: str
    description: str
    type: str
    condition: dict[str, Any]
    rationale: str
    factor: float = 1.0
    layer: str | None = None
    weight_multiplier: float = 1.0
    only_if_lowers: bool = True
    exclusive_group: str | None = None


@dataclass(frozen=True)
class GuardSpec:
    """Card-testing guard: when the condition holds the total factor is floored at min_total."""

    id: str
    name: str
    condition: dict[str, Any]
    min_total: float
    rationale: str


@dataclass(frozen=True)
class ContextConfig:
    """The whole context.yaml (rules + bounds + guard + learned-param definitions)."""

    rules: list[RuleSpec]
    guard: GuardSpec
    min_total: float
    max_total: float
    clip_min: float
    clip_max: float
    learned_params: dict[str, dict[str, Any]]
    derived: dict[str, Any]
    params_dir: str
    use_guard: bool = True
    use_bounds: bool = True
    disabled_groups: frozenset[str] = field(default_factory=frozenset)

    def active_rules(self) -> list[RuleSpec]:
        """Rules whose group is not disabled (used by the ablation)."""
        return [r for r in self.rules if r.group not in self.disabled_groups]

    def groups(self) -> list[str]:
        """Rule groups in config order (C6a/C6b -> C6)."""
        return list(dict.fromkeys(r.group for r in self.rules))

    def variant(
        self,
        disabled: set[str] | None = None,
        use_guard: bool = True,
        use_bounds: bool = True,
    ) -> ContextConfig:
        """Copy with some groups switched off and/or without guard or bounds (ablation)."""
        return replace(
            self,
            disabled_groups=frozenset(disabled or set()),
            use_guard=use_guard,
            use_bounds=use_bounds,
        )


def _rule(raw: dict[str, Any]) -> RuleSpec:
    """Build and check one rule."""
    if raw["type"] not in RULE_TYPES:
        raise ValueError(f"rule {raw['id']}: unknown type {raw['type']}")
    for key in ("id", "name", "condition", "rationale"):
        if not raw.get(key):
            raise ValueError(f"rule {raw.get('id')}: missing {key}")
    if raw["type"] == "layer_weight" and not raw.get("layer"):
        raise ValueError(f"rule {raw['id']}: layer_weight rules need `layer`")
    return RuleSpec(
        id=raw["id"],
        group=raw.get("group", raw["id"]),
        name=raw["name"],
        description=str(raw.get("description", "")).strip(),
        type=raw["type"],
        condition=raw["condition"],
        rationale=str(raw["rationale"]).strip(),
        factor=float(raw.get("factor", 1.0)),
        layer=raw.get("layer"),
        weight_multiplier=float(raw.get("weight_multiplier", 1.0)),
        only_if_lowers=bool(raw.get("only_if_lowers", True)),
        exclusive_group=raw.get("exclusive_group"),
    )


def parse_context_config(raw: dict[str, Any]) -> ContextConfig:
    """Turn the YAML dict into a ContextConfig (raises on invalid input)."""
    rules = [_rule(r) for r in raw["rules"]]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate rule ids in context config")
    g = raw["guard"]
    guard = GuardSpec(
        id=g["id"],
        name=g["name"],
        condition=g["condition"],
        min_total=float(g["min_total"]),
        rationale=str(g["rationale"]).strip(),
    )
    bounds = raw["bounds"]
    if not 0 < bounds["min_total"] <= 1 <= bounds["max_total"]:
        raise ValueError("bounds must satisfy 0 < min_total <= 1 <= max_total")
    clip = raw.get("score_clip", {"min": 0.0, "max": 1.0})
    return ContextConfig(
        rules=rules,
        guard=guard,
        min_total=float(bounds["min_total"]),
        max_total=float(bounds["max_total"]),
        clip_min=float(clip["min"]),
        clip_max=float(clip["max"]),
        learned_params=raw.get("learned_params", {}),
        derived=raw.get("derived", {}),
        params_dir=raw.get("paths", {}).get("params_dir", "reports/context"),
    )


def load_context_config(config_dir: Path = CONFIG_DIR) -> ContextConfig:
    """Load configs/context.yaml."""
    return parse_context_config(load_yaml("context.yaml", config_dir))
