"""Fakes for agent tests: no models, no artifacts, no Ollama."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import pytest

from src.agents.bus import MessageBus
from src.agents.config import AgentSettings, load_agent_settings
from src.agents.coordinator import CoordinatorAgent
from src.agents.factory import AgentFactory
from src.agents.planner import Planner
from src.core.interfaces import ContextAdjuster, LLMClient
from src.core.types import AdjustedResult, Explanation, ScoreResult
from src.rag.errors import LLMUnavailableError
from src.rag.service import RAGAnswer, SourceRef
from src.rules.engine import RuleEngineResult

RECORD: dict[str, Any] = {"TransactionID": 42, "TransactionAmt": 12.5, "card1": 1}


class FakeScoring:
    """score_one returns a fixed score; can fail."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def score_one(self, features: dict[str, Any]) -> ScoreResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("scoring down")
        return ScoreResult(
            score=0.7,
            raw_score=0.6,
            layer_scores={"column": 0.5, "temporal": 0.9},
            explanations=[Explanation(source="column", message="m")],
        )


class FakeAdjuster(ContextAdjuster):
    """Adds one C rule; remembers the record it saw."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_record: dict[str, Any] = {}

    def adjust_batch(self, df: pd.DataFrame, raw_score: pd.Series) -> pd.DataFrame:
        raise NotImplementedError

    def adjust_one(self, record: dict[str, Any], raw_score: float) -> AdjustedResult:
        self.calls += 1
        self.last_record = record
        return AdjustedResult(
            raw_score=raw_score,
            adjusted_score=0.5,
            applied_rules=["C3"],
            explanations=[
                Explanation(
                    source="context",
                    message="total",
                    details={"adjusted_score_unclipped": 0.55},
                )
            ],
        )


class FakeEngine:
    """Rule engine stand-in: returns `decision` and records its calls."""

    def __init__(
        self,
        decision: str = "review",
        triggered: list[str] | None = None,
        source: str | None = None,
    ) -> None:
        self.source = source
        self.decision = decision
        self.triggered = ["R01"] if triggered is None else triggered
        self.calls: list[dict[str, Any]] = []

    def evaluate(
        self, record: dict[str, Any], anomaly_score: float, update_state: bool = True
    ) -> RuleEngineResult:
        self.calls.append({"record": record, "score": anomaly_score, "update_state": update_state})
        return RuleEngineResult(
            action=self.decision,
            final_decision=self.decision,
            decision_source=self.source or (self.triggered[0] if self.triggered else "default"),
            final_score=0.8,
            triggered_rules=self.triggered,
            applied_rules=self.triggered,
            triggered_details=[{"id": r} for r in self.triggered],
            reasons=["reason"],
            adjusted_score=0.5,
            adjusted_score_unclipped=anomaly_score,
            final_score_unclipped=0.8,
        )


class FakeRAG:
    """RAGService stand-in with a canned answer; can fail or be slow."""

    def __init__(
        self, text: str = "Açıklama [a#b]", fail: bool = False, delay: float = 0.0
    ) -> None:
        self.text, self.fail, self.delay = text, fail, delay
        self.calls: list[dict[str, Any]] = []

    def answer(self, question: str, explanation: Any = None, rule_ids: Any = None) -> RAGAnswer:
        self.calls.append({"question": question, "rule_ids": rule_ids})
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("rag down")
        return RAGAnswer(
            question=question,
            answer=self.text,
            sources=[SourceRef(chunk_id="a#b", heading="A > B")],
            cited_ids=["a#b"],
            grounded=True,
        )


class FakePlannerLLM(LLMClient):
    """Planner LLM with a canned answer; can be down or slow."""

    def __init__(self, answer: str = "", down: bool = False, delay: float = 0.0) -> None:
        self.answer, self.down, self.delay = answer, down, delay
        self.calls = 0

    def generate(self, prompt: str, context: str = "") -> str:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.down:
            raise LLMUnavailableError("planner llm down")
        return self.answer


def plan_json(*steps: str) -> str:
    """LLM answer for steps like 'rule:evaluate'."""
    items = ",".join(
        '{"agent":"%s","intent":"%s"}' % tuple(s.split(":")) for s in steps  # noqa: UP031
    )
    return '{"steps":[' + items + "]}"


class System:
    """A wired agent system with its fakes."""

    def __init__(
        self,
        settings: AgentSettings,
        scoring: FakeScoring,
        adjuster: FakeAdjuster,
        engine: FakeEngine,
        rag: FakeRAG,
        llm: FakePlannerLLM,
    ) -> None:
        self.settings, self.scoring, self.adjuster = settings, scoring, adjuster
        self.engine, self.rag, self.llm = engine, rag, llm
        self.bus = MessageBus(settings.bus.max_depth)
        self.planner = Planner(llm, settings)
        factory = AgentFactory(
            self.bus, settings, scoring, adjuster, engine, rag, self.planner  # type: ignore[arg-type]
        )
        self.coordinator: CoordinatorAgent = factory.create_system()


@pytest.fixture
def settings() -> AgentSettings:
    """The real configs/agents.yaml."""
    return load_agent_settings()


@pytest.fixture
def make_system(settings: AgentSettings):
    """Factory fixture: make_system(scoring=..., engine=..., rag=..., llm=..., settings=...)."""

    def build(
        scoring: FakeScoring | None = None,
        engine: FakeEngine | None = None,
        rag: FakeRAG | None = None,
        llm: FakePlannerLLM | None = None,
        cfg: AgentSettings | None = None,
    ) -> System:
        return System(
            cfg or settings,
            scoring or FakeScoring(),
            FakeAdjuster(),
            engine or FakeEngine(),
            rag or FakeRAG(),
            llm or FakePlannerLLM(),
        )

    return build
