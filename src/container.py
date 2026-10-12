"""DI container. Later steps only ADD providers; never remove existing ones."""

from __future__ import annotations

import httpx
from dependency_injector import containers, providers

from src.agents.bus import MessageBus
from src.agents.config import load_agent_settings
from src.agents.factory import AgentFactory, build_planner_llm, create_coordinator
from src.agents.planner import Planner
from src.api.artifacts import resolve_artifact_set
from src.api.config import agent_settings_for_api, load_api_settings
from src.api.health import HealthService
from src.api.online import OnlineScorer
from src.api.services import ExplainService, RagQueryService
from src.api.warmup import ModelWarmer
from src.context.factory import load_engine
from src.core.config import CONFIG_DIR, get_sample_n
from src.features.pipeline import FeaturePipeline
from src.rag.config import load_rag_settings
from src.rag.embedder import OllamaEmbedder
from src.rag.llm import OllamaLLMClient
from src.rag.prompt import PromptBuilder
from src.rag.retriever import HybridRetriever
from src.rag.service import RAGService
from src.rag.store import load_vector_store
from src.rules.cooldown import CooldownStore
from src.rules.factory import load_rule_engine
from src.rules.repository import RuleRepository
from src.scoring.service import ScoringService


class Container(containers.DeclarativeContainer):
    """Single application container (providers are added by later steps)."""

    config = providers.Configuration()

    # Step 8-10 review (Ö4): full-data or SAMPLE_N artifact paths, from the SAMPLE_N env var.
    artifact_set = providers.Singleton(resolve_artifact_set, providers.Callable(get_sample_n))

    # Step 3: fitted feature pipeline + entity store (loaded lazily; the API never trains).
    feature_pipeline = providers.Singleton(
        FeaturePipeline.load,
        artifact_set.provided.feature_pipeline,
        artifact_set.provided.entity_profiles,
    )

    # Step 4-5: fitted anomaly layers + weights + normalization tables (loaded, never trained).
    scoring_service = providers.Singleton(ScoringService.load, artifact_set.provided.detectors_dir)

    # Step 6: context adjuster (configs/context.yaml + fit-learned params + Step 5 weights/table).
    context_adjuster = providers.Singleton(
        load_engine, artifact_set.provided.detectors_dir, artifact_set.provided.context_params_dir
    )

    # Step 7: rule repository (configs/rules.yaml + rules_extra.json, reload()) and rule engine
    # (thresholds learned on the fit set, stored in rules.yaml `learned:`; never fitted here).
    rule_repository = providers.Singleton(RuleRepository, CONFIG_DIR / "rules.yaml")
    # Step 7 review (K7-2): online cooldown state, injected into the engine (override in tests).
    cooldown_store = providers.Singleton(CooldownStore)
    rule_engine = providers.Singleton(
        load_rule_engine,
        rule_repository,
        cooldown_store=cooldown_store,
        sample=artifact_set.provided.sample,
        sample_dir=artifact_set.provided.rules_sample_dir,
    )

    # Step 8: local RAG (configs/rag.yaml). The FAISS index is only loaded (built offline by
    # `make rag-index`); resolving the store without an index raises IndexNotBuiltError.
    rag_settings = providers.Singleton(load_rag_settings, CONFIG_DIR)
    # Step 8-10 review (K5): one HTTP client per Ollama host, injected into the clients below.
    # Timeouts are sent per request from each client's config.
    embedding_http_client = providers.Singleton(
        httpx.Client, base_url=rag_settings.provided.embedding.host
    )
    llm_http_client = providers.Singleton(httpx.Client, base_url=rag_settings.provided.llm.host)
    embedder = providers.Singleton(
        OllamaEmbedder, rag_settings.provided.embedding, embedding_http_client
    )
    llm_client = providers.Singleton(OllamaLLMClient, rag_settings.provided.llm, llm_http_client)
    vector_store = providers.Singleton(load_vector_store, rag_settings)
    retriever = providers.Singleton(
        HybridRetriever, embedder, vector_store, rag_settings.provided.retrieval
    )
    prompt_builder = providers.Singleton(PromptBuilder, rag_settings.provided.prompt)
    rag_service = providers.Singleton(
        RAGService,
        retriever,
        llm_client,
        prompt_builder,
        abstain_threshold=rag_settings.provided.retrieval.abstain_threshold,
        abstain_answer=rag_settings.provided.prompt.abstain_answer,
        ungrounded_warning=rag_settings.provided.prompt.ungrounded_warning,
    )

    # Step 9: runtime agents (configs/agents.yaml). The bus is the Mediator; AgentFactory builds
    # the agents from the services above (override any of them with a mock in tests).
    agents_settings = providers.Singleton(load_agent_settings, CONFIG_DIR)
    message_bus = providers.Singleton(MessageBus, agents_settings.provided.bus.max_depth)
    planner_llm = providers.Singleton(
        build_planner_llm, rag_settings.provided.llm, agents_settings, llm_http_client
    )
    planner = providers.Singleton(Planner, planner_llm, agents_settings)
    agent_factory = providers.Singleton(
        AgentFactory,
        message_bus,
        agents_settings,
        scoring_service,
        context_adjuster,
        rule_engine,
        rag_service.provider,
        planner,
    )
    coordinator = providers.Singleton(create_coordinator, agent_factory)

    # Step 10: API. `online_scorer` holds the online entity history (loaded from artifacts/, one
    # process, in memory). The API agent flow is a second, separate bus + agents built from the
    # same services with the API's LLM deadline (configs/api.yaml, default 60 s); the Step 9
    # `coordinator` above stays unchanged for scripts and demos.
    api_settings = providers.Singleton(load_api_settings, CONFIG_DIR)
    online_scorer = providers.Singleton(
        OnlineScorer, feature_pipeline, scoring_service, context_adjuster, rule_engine, api_settings
    )
    api_agents_settings = providers.Singleton(agent_settings_for_api, agents_settings, api_settings)
    api_message_bus = providers.Singleton(MessageBus, agents_settings.provided.bus.max_depth)
    api_planner_llm = providers.Singleton(
        build_planner_llm, rag_settings.provided.llm, api_agents_settings, llm_http_client
    )
    api_planner = providers.Singleton(Planner, api_planner_llm, api_agents_settings)
    api_agent_factory = providers.Singleton(
        AgentFactory,
        api_message_bus,
        api_agents_settings,
        scoring_service,
        context_adjuster,
        rule_engine,
        rag_service.provider,
        api_planner,
    )
    api_coordinator = providers.Singleton(create_coordinator, api_agent_factory)
    explain_service = providers.Singleton(ExplainService, online_scorer, api_coordinator)
    rag_query_service = providers.Singleton(RagQueryService, rag_service, api_settings)
    health_http_client = providers.Singleton(httpx.Client)
    # K-50: startup warm-up of the Ollama models (background thread; state shown by /health).
    model_warmer = providers.Singleton(ModelWarmer, embedder, llm_client, api_settings)
    health_service = providers.Singleton(
        HealthService,
        online_scorer.provider,
        rag_settings,
        api_settings,
        health_http_client,
        model_warmer,
    )


def create_container() -> Container:
    """Create the container and load configs/settings.yaml into it."""
    container = Container()
    container.config.from_yaml(str(CONFIG_DIR / "settings.yaml"))
    return container
