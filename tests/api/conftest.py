"""Fakes for API tests: no artifacts, no Ollama, no real data. The rule engine is the real one
(configs/rules.yaml with fixed thresholds), everything else is a small stand-in."""

from __future__ import annotations

import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from src.agents.bus import MessageBus
from src.agents.config import load_agent_settings
from src.agents.factory import AgentFactory
from src.agents.planner import Planner
from src.api.config import ApiSettings, LLMSettings, agent_settings_for_api
from src.api.health import HealthService
from src.api.main import create_app
from src.api.online import OnlineScorer
from src.api.services import ExplainService, RagQueryService
from src.container import Container
from src.core.config import CONFIG_DIR
from src.core.interfaces import ContextAdjuster, LLMClient
from src.core.types import AdjustedResult, Explanation, ScoreResult
from src.rag.config import load_rag_settings
from src.rag.errors import EmbeddingUnavailableError, LLMUnavailableError
from src.rag.service import RAGAnswer, SourceRef
from src.rules.cooldown import CooldownStore
from src.rules.engine import RuleEngine
from src.rules.repository import RuleRepository

PARAMS = {
    "amount_small": 25.0,
    "amount_high": 400.0,
    "velocity_1h_extreme": 10.0,
    "score_review_threshold": 0.9,
    "trusted_min_history": 100.0,
}

# History features of an uneventful entity (they trigger no rule); tests change single values.
NEUTRAL_FEATURES: dict[str, Any] = {
    "hour": 10,
    "small_amt_streak_1h": 0,
    "ent_cnt_1h": 0,
    "ent_txn_count": 10,
    "ent_age_days": 10.0,
    "ent_avg_amt": 100.0,
    "amt_ratio_to_ent_avg": 1.0,
    "amt_zscore_ent": 0.0,
    "is_first_seen": False,
    "card_age_days": 50.0,
    "foreign_addr2": False,
    "addr2_missing": False,
    "is_low_volume_window": 0,
    "local_hour_est": 12,
    "is_weekend": 0,
    "has_identity": True,
    "email_mismatch": False,
    "amt_has_3dec": False,
    "holiday_season": 0,
    "device_ent_match": 0,
    "time_since_last_txn": 600.0,
}

PAYLOAD: dict[str, Any] = {
    "TransactionID": 100,
    "TransactionDT": 86400,
    "TransactionAmt": 120.0,
    "ProductCD": "W",
    "card1": 1000,
    "addr1": 300,
    "addr2": 87,
    "P_emaildomain": "gmail.com",
}


class FakeEntity:
    """EntityState stand-in: only the e-mail set is read."""

    def __init__(self, emails: set[str]) -> None:
        self.emails = emails


class FakeStore:
    """EntityStore stand-in that records updates."""

    def __init__(self) -> None:
        self.entities: dict[str, FakeEntity] = {}
        self.updates: list[tuple[Any, ...]] = []

    def update(self, ent: str, card: str, dev: str, email: str, dt: int, amt: float) -> None:
        self.updates.append((ent, card, dev, email, dt, amt))
        self.entities.setdefault(ent, FakeEntity(set())).emails.add(email)


class FakePipeline:
    """FeaturePipeline stand-in: fixed features, a recording store."""

    def __init__(self) -> None:
        self.config = {"history": {"device_column": "DeviceInfo", "email_column": "P_emaildomain"}}
        self.entity_columns = ["card1", "addr1"]
        self.store = FakeStore()
        self.features = dict(NEUTRAL_FEATURES)
        self.calls = 0

    def transform_one(self, txn: dict[str, Any], update: bool = False) -> dict[str, Any]:
        assert not update, "the API must never ask the pipeline to update"
        self.calls += 1
        return dict(self.features)


class FakeHourStore:
    """HourStore stand-in."""

    def __init__(self) -> None:
        self.counts: dict[str, Any] = {}
        self.updates: list[tuple[str, int]] = []

    def update(self, key: str, hour: int) -> None:
        self.updates.append((key, hour))


class FakeScoring:
    """ScoringService stand-in: a fixed score; remembers the records it saw."""

    def __init__(self, score: float = 0.4) -> None:
        self.score = score
        self.records: list[dict[str, Any]] = []
        self.detectors = {"temporal": SimpleNamespace(store=FakeHourStore(), hours=24)}

    def score_one(self, record: dict[str, Any]) -> ScoreResult:
        self.records.append(record)
        return ScoreResult(
            score=self.score,
            raw_score=self.score - 0.1,
            layer_scores={"column": 0.5, "multivariate": 0.3, "entity": 0.2, "temporal": 0.6},
        )


class FakeAdjuster(ContextAdjuster):
    """Applies one context rule (C1, x0.9)."""

    def adjust_batch(self, df: Any, raw_score: Any) -> Any:
        raise NotImplementedError

    def adjust_one(self, record: dict[str, Any], raw_score: float) -> AdjustedResult:
        unclipped = raw_score * 0.9
        entry = {"id": "C1", "name": "business_hours", "factor": 0.9, "reason": "test"}
        return AdjustedResult(
            raw_score=raw_score,
            adjusted_score=min(unclipped, 1.0),
            applied_rules=["C1"],
            explanations=[
                Explanation(source="context", message="C1", details=entry),
                Explanation(
                    source="context",
                    message="total",
                    details={"adjusted_score_unclipped": unclipped},
                ),
            ],
        )


class ForbiddenLLM(LLMClient):
    """Any use fails the test: proves a code path does not call the LLM."""

    def generate(self, prompt: str, context: str = "") -> str:
        raise AssertionError("the LLM must not be called on this path")


class FakeRAG:
    """RAGService stand-in with a canned answer; can be down, slow or raise."""

    def __init__(
        self,
        text: str | None = "Açıklama [a#b]",
        flags: list[str] | None = None,
        delay: float = 0.0,
        error: Exception | None = None,
        abstained: bool = False,
    ) -> None:
        self.text, self.flags, self.delay = text, flags or [], delay
        self.error, self.abstained = error, abstained
        self.calls: list[dict[str, Any]] = []

    def answer(
        self,
        question: str,
        explanation: Any = None,
        rule_ids: list[str] | None = None,
        k: int | None = None,
    ) -> RAGAnswer:
        self.calls.append({"question": question, "rule_ids": rule_ids, "k": k})
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        grounded = self.text is not None and not self.flags and not self.abstained
        return RAGAnswer(
            question=question,
            answer=self.text,
            sources=[SourceRef(chunk_id="a#b", heading="A > B", score=0.7)],
            cited_ids=["a#b"] if grounded else [],
            flags=self.flags,
            grounded=grounded,
            abstained=self.abstained,
        )


class NoPlanLLM(LLMClient):
    """Planner LLM that is down (the planner then uses the default plan)."""

    def generate(self, prompt: str, context: str = "") -> str:
        raise LLMUnavailableError("planner llm down")


class World:
    """All fakes of one test in one place."""

    def __init__(self, rag: FakeRAG | None = None, llm_timeout: float = 60.0) -> None:
        # Same 1/6 planner, 5/6 explainer split as configs/api.yaml (10 s + 50 s of 60 s).
        self.api_settings = ApiSettings(
            llm=LLMSettings(
                timeout_seconds=llm_timeout,
                planner_timeout_seconds=llm_timeout / 6,
                explainer_timeout_seconds=llm_timeout * 5 / 6,
            )
        )
        self.pipeline = FakePipeline()
        self.scoring = FakeScoring()
        self.adjuster = FakeAdjuster()
        self.cooldown = CooldownStore()
        repo = RuleRepository(CONFIG_DIR / "rules.yaml")
        self.engine = RuleEngine(repo, PARAMS, self.cooldown)
        self.rag = rag or FakeRAG()
        self.scorer = OnlineScorer(
            self.pipeline,  # type: ignore[arg-type]
            self.scoring,  # type: ignore[arg-type]
            self.adjuster,
            self.engine,
            self.api_settings,
        )
        agents = agent_settings_for_api(load_agent_settings(), self.api_settings)
        bus = MessageBus(agents.bus.max_depth)
        factory = AgentFactory(
            bus,
            agents,
            self.scoring,  # type: ignore[arg-type]
            self.adjuster,
            self.engine,
            lambda: self.rag,  # type: ignore[arg-type,return-value]
            Planner(NoPlanLLM(), agents),
        )
        self.coordinator = factory.create_system()
        self.explain_service = ExplainService(self.scorer, self.coordinator)
        self.rag_service = RagQueryService(self.rag, self.api_settings)  # type: ignore[arg-type]


@pytest.fixture
def world() -> World:
    return World()


def make_client(world: World, ollama: httpx.Client | None = None) -> Iterator[TestClient]:
    """A TestClient whose container uses the fakes of `world` (providers overridden)."""
    container = Container()
    container.online_scorer.override(world.scorer)
    container.explain_service.override(world.explain_service)
    container.rag_query_service.override(world.rag_service)
    container.rule_engine.override(world.engine)
    # any real LLM / RAG / agent object reachable from the container must stay unused on /score
    container.llm_client.override(ForbiddenLLM())
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "bge-m3:latest"}]}
        )
    )
    client = ollama or httpx.Client(transport=transport)
    container.health_http_client.override(client)
    container.health_service.override(
        HealthService(
            lambda: world.scorer,
            load_rag_settings(CONFIG_DIR),
            world.api_settings,
            client,
        )
    )
    app = create_app(container)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    container.unwire()


@pytest.fixture
def client(world: World) -> Iterator[TestClient]:
    yield from make_client(world)


def down_client() -> httpx.Client:
    """An httpx client for which Ollama is unreachable."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    return httpx.Client(transport=httpx.MockTransport(refuse))


__all__ = [
    "EmbeddingUnavailableError",
    "FakeRAG",
    "ForbiddenLLM",
    "NEUTRAL_FEATURES",
    "PAYLOAD",
    "World",
    "down_client",
    "make_client",
]
