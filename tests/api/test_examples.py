"""The ready-made request files in examples/requests/ match the API schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.config import load_api_settings
from src.api.schemas import ExplainRequest, RagQueryRequest, RulesEvaluateRequest, TransactionIn
from src.rules.repository import RuleRepository, RuleValidationError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "requests"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


@pytest.mark.parametrize("name", ["block.json", "review.json", "allow.json"])
def test_score_examples_are_valid_transactions(name: str) -> None:
    TransactionIn.model_validate(_load(name))


def test_explain_and_rag_examples_are_valid() -> None:
    ExplainRequest.model_validate(_load("explain_review.json"))
    ExplainRequest.model_validate(_load("explain_question.json"))
    RagQueryRequest.model_validate(_load("rag_query.json"))


def test_invalid_rule_set_example_is_a_valid_request_but_an_invalid_rule_set() -> None:
    body = RulesEvaluateRequest.model_validate(_load("rules_invalid.json"))
    assert body.rules is not None
    with pytest.raises(RuleValidationError):
        RuleRepository().parse(body.rules)


def test_api_yaml_sets_the_60_second_llm_deadline() -> None:
    assert load_api_settings().llm.timeout_seconds == 60
