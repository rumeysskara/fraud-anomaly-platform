"""Loading YAML + JSON, reload(), schema rejection and request-time rule sets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.core.config import CONFIG_DIR
from src.rules.repository import RuleRepository, RuleValidationError

JSON_RULE = {
    "id": "X1",
    "name": "big_amount",
    "priority": 2,
    "severity": "high",
    "condition": {"any": [{"feature": "TransactionAmt", "op": ">", "value": 1000}]},
    "action": {"risk_boost": 0.1, "decision": "review", "flag": "big"},
    "message": "Tutar {TransactionAmt:.2f}",
}


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Copy of configs/rules.yaml + rules_extra.json (+ entity.yaml for the key) in a temp dir."""
    for name in ("rules.yaml", "rules_extra.json", "entity.yaml"):
        shutil.copy(CONFIG_DIR / name, tmp_path / name)
    return tmp_path


def write_json(path: Path, rules: list[dict]) -> None:
    path.write_text(json.dumps({"rules": rules}))


def test_yaml_and_json_rules_are_loaded(repo):
    ids = [r.id for r in repo.rules]
    assert ids[:10] == [f"R{i:02d}" for i in range(1, 11)]
    assert {"R11", "R12"} <= set(ids)  # from configs/rules_extra.json
    assert len(ids) >= 10


def test_reload_picks_up_a_new_json_rule(config_dir):
    repo = RuleRepository(config_dir / "rules.yaml")
    write_json(config_dir / "rules_extra.json", [JSON_RULE])
    rules = repo.reload()
    assert "X1" in {r.id for r in rules} and "R11" not in {r.id for r in rules}


def test_invalid_file_keeps_previous_set(config_dir):
    repo = RuleRepository(config_dir / "rules.yaml")
    before = [r.id for r in repo.rules]
    write_json(config_dir / "rules_extra.json", [{**JSON_RULE, "severity": "extreme"}])
    with pytest.raises(RuleValidationError):
        repo.reload()
    assert [r.id for r in repo.rules] == before


@pytest.mark.parametrize(
    "change, match",
    [
        ({"severity": "extreme"}, "severity"),
        ({"priority": 0}, "priority"),
        ({"condition": {"feature": "TransactionAmt", "op": "~", "value": 1}}, "X1"),
        ({"condition": {"feature": "TransactionAmt", "op": "between", "value": [1]}}, "between"),
        ({"condition": {"feature": "TransactionAmt", "op": "in", "value": 3}}, "list"),
        ({"action": {"risk_boost": 0.2, "decision": "allow", "flag": "a"}}, "allow"),
        ({"action": {"risk_boost": 0.1, "decision": "deny", "flag": "a"}}, "decision"),
        ({"unknown_key": 1}, "unknown_key"),
        ({"condition": {"feature": "isFraud", "op": "==", "value": 1}}, "unknown feature"),
        (
            {"condition": {"feature": "TransactionAmt", "op": ">", "value": {"param": "nope"}}},
            "param",
        ),
        ({"message": "Tutar {secret}"}, "message field"),
    ],
)
def test_invalid_rule_is_rejected(repo, change, match):
    with pytest.raises(RuleValidationError, match=match):
        repo.parse([{**JSON_RULE, **change}])


def test_duplicate_ids_are_rejected(repo):
    with pytest.raises(RuleValidationError, match="duplicate"):
        repo.parse([JSON_RULE, JSON_RULE])


def test_duplicate_id_across_files_is_rejected(config_dir):
    write_json(config_dir / "rules_extra.json", [{**JSON_RULE, "id": "R01"}])
    with pytest.raises(RuleValidationError, match="duplicate"):
        RuleRepository(config_dir / "rules.yaml")


def test_yaml_only_setup(config_dir):
    data = yaml.safe_load((config_dir / "rules.yaml").read_text())
    data["files"]["rules"] = ["rules.yaml"]
    (config_dir / "rules.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
    repo = RuleRepository(config_dir / "rules.yaml")
    assert "R11" not in {r.id for r in repo.rules}


def test_request_time_rule_set_json_text(engine, neutral):
    payload = json.dumps({"rules": [JSON_RULE]})
    result = engine.evaluate({**neutral, "TransactionAmt": 1500.0}, 0.2, rules=payload)
    assert result.triggered_rules == ["X1"] and result.final_decision == "review"
    assert result.reasons == ["Tutar 1500.00"]
    # the loaded set is unchanged
    assert "X1" not in {r.id for r in engine.repository.rules}


def test_request_time_rule_set_is_validated(engine, neutral):
    with pytest.raises(RuleValidationError):
        engine.evaluate(neutral, 0.2, rules=[{**JSON_RULE, "op": "bad"}])
