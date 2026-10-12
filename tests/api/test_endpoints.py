"""Endpoint tests with TestClient and container overrides (fake LLM/RAG, real rule engine)."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from src.rag.errors import EmbeddingUnavailableError, IndexNotBuiltError
from tests.api.conftest import PAYLOAD, World, down_client, make_client

BLOCK_RULE = {
    "id": "X1",
    "name": "big_amount",
    "priority": 1,
    "severity": "high",
    "condition": {"feature": "TransactionAmt", "op": ">=", "value": 100},
    "action": {"risk_boost": 0.2, "decision": "block", "flag": "big"},
    "message": "Tutar {TransactionAmt:.0f} USD",
}


def body(**changes: Any) -> dict[str, Any]:
    return {**PAYLOAD, **changes}


# ---- /score -----------------------------------------------------------------------------------


def test_score_response_shape(client: TestClient) -> None:
    response = client.post("/score", json=body())
    assert response.status_code == 200
    data = response.json()
    for key in (
        "anomaly_score",
        "raw_anomaly_score",
        "layer_scores",
        "adjusted_score",
        "context_rules",
        "final_score",
        "final_decision",
        "decision_source",
        "triggered_rules",
        "suppressed_rules",
        "reasons",
    ):
        assert key in data
    assert data["final_decision"] == "allow" and data["duplicate"] is False
    assert data["context_rules"][0]["id"] == "C1"
    assert "isfraud" not in json.dumps(data).lower()
    assert response.headers["X-Request-ID"]


def test_score_triggers_a_loaded_rule(client: TestClient, world: World) -> None:
    world.pipeline.features["small_amt_streak_1h"] = 3
    data = client.post("/score", json=body(TransactionAmt=5.0)).json()
    assert data["final_decision"] == "block" and data["decision_source"] == "R01"
    assert data["triggered_rules"][0]["id"] == "R01"
    assert "küçük tutar" in " ".join(data["reasons"])


def test_score_is_idempotent_and_cooldown_is_written_once(client: TestClient, world: World) -> None:
    world.pipeline.features.update({"ent_cnt_1h": 15})
    first = client.post("/score", json=body()).json()
    second = client.post("/score", json=body()).json()
    assert first["triggered_rules"] == second["triggered_rules"] != []
    assert second["duplicate"] is True and second["state_updated"] is False
    assert world.cooldown.size()[1] == 1
    assert len(world.pipeline.store.updates) == 1


def test_score_never_calls_the_llm(client: TestClient, world: World) -> None:
    assert client.post("/score", json=body()).status_code == 200
    assert world.rag.calls == []


def test_score_missing_required_field_is_422(client: TestClient) -> None:
    payload = body()
    del payload["TransactionAmt"]
    response = client.post("/score", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "TransactionAmt"
    assert error["request_id"]


def test_score_rejects_bad_types_negative_amount_and_unknown_fields(client: TestClient) -> None:
    assert client.post("/score", json=body(TransactionAmt="abc")).status_code == 422
    assert client.post("/score", json=body(TransactionAmt=-1)).status_code == 422
    unknown = client.post("/score", json=body(Foo=1))
    assert unknown.status_code == 422 and "Foo" in json.dumps(unknown.json())
    assert client.post("/score", json=body(V12=1.5, id_30="Windows 10")).status_code == 200


# ---- /explain ---------------------------------------------------------------------------------


def explain(client: TestClient, question: str | None = None, **changes: Any) -> dict[str, Any]:
    response = client.post("/explain", json={"transaction": body(**changes), "question": question})
    assert response.status_code == 200
    return response.json()


def test_explain_returns_facts_narrative_and_trace(client: TestClient, world: World) -> None:
    data = explain(client)
    assert data["llm_status"] == "ok"
    assert data["narrative"]["label"] == "destek bilgisi"
    assert data["narrative"]["affects_decision"] is False and data["narrative"]["grounded"]
    facts = data["facts"]
    assert facts["decision"] == "allow" and facts["layer_scores"]["column"] == 0.5
    assert facts["thresholds"]["score_review"] == 0.9
    assert facts["context_rules"][0]["id"] == "C1"
    assert "Karar: allow" in facts["summary"]
    assert [t["recipient"] for t in data["trace"]][:2] == ["coordinator", "anomaly"]
    assert world.pipeline.store.updates == []  # /explain writes no state
    assert world.cooldown.size() == (0, 0)


def test_explain_facts_are_complete_without_the_llm(client: TestClient, world: World) -> None:
    from src.rag.errors import LLMUnavailableError

    world.rag.error = LLMUnavailableError("ollama down")
    data = explain(client)
    assert data["narrative"] is None and data["llm_status"] == "unavailable"
    assert data["facts"]["decision"] == "allow" and data["facts"]["summary"]


def test_explain_unexpected_agent_failure_is_error_status_with_facts(world: World) -> None:
    def broken(request: Any) -> Any:
        raise RuntimeError("agent system crashed")

    world.coordinator.analyze = broken  # type: ignore[method-assign,assignment]
    for client in make_client(world):
        data = explain(client)
        assert data["llm_status"] == "error" and data["narrative"] is None
        assert data["trace"] == [] and data["facts"]["decision"] == "allow"


def test_explain_retrieval_only_answer_gives_unavailable_and_template_facts(
    world: World,
) -> None:
    world.rag.text, world.rag.flags = None, ["llm_unavailable"]
    for client in make_client(world):
        data = explain(client)
        assert data["narrative"] is None and data["llm_status"] == "unavailable"
        assert data["facts"]["reasons"] and data["facts"]["layer_scores"]


def test_explain_embedding_down_is_unavailable_not_500(world: World) -> None:
    world.rag.error = EmbeddingUnavailableError("Ollama embedding endpoint unreachable")
    for client in make_client(world):
        data = explain(client)
        assert data["llm_status"] == "unavailable" and data["narrative"] is None
        assert data["facts"]["decision"] == "allow"


def test_explain_timeout_returns_facts_with_timeout_status() -> None:
    from tests.api.conftest import FakeRAG

    world = World(rag=FakeRAG(delay=1.0), llm_timeout=0.2)
    for client in make_client(world):
        data = explain(client)
        assert data["llm_status"] == "timeout" and data["narrative"] is None
        assert data["facts"]["decision"] == "allow"
        assert data["agent"]["status"] == "degraded"


def test_explain_with_question_still_returns_facts_when_planner_llm_is_down(
    client: TestClient,
) -> None:
    data = explain(client, question="Bu işlemi incele ve not yaz.")
    assert data["agent"]["plan_source"] == "fallback"
    assert data["facts"]["decision"] == "allow"


def test_explain_requires_the_transaction(client: TestClient) -> None:
    assert client.post("/explain", json={"question": "x"}).status_code == 422


# ---- /rules -----------------------------------------------------------------------------------


def test_rules_list_and_reload(client: TestClient) -> None:
    data = client.get("/rules").json()
    assert data["count"] >= 10 and data["rules"][0]["id"] == "R01"
    assert {"priority", "severity", "decision", "risk_boost"} <= set(data["rules"][0])
    reloaded = client.post("/rules/reload")
    assert reloaded.status_code == 200 and reloaded.json()["count"] == data["count"]


def test_rules_evaluate_with_loaded_rules_reads_cooldown_only(
    client: TestClient, world: World
) -> None:
    world.pipeline.features.update({"ent_cnt_1h": 15})
    response = client.post("/rules/evaluate", json={"transaction": body()})
    data = response.json()
    assert response.status_code == 200 and data["rule_set"] == "loaded"
    assert "R03" in [r["id"] for r in data["triggered_rules"]]
    assert world.cooldown.size() == (0, 0)  # evaluate does not write the cooldown state


def test_rules_evaluate_with_request_rules(client: TestClient) -> None:
    data = client.post(
        "/rules/evaluate", json={"transaction": body(), "rules": [BLOCK_RULE]}
    ).json()
    assert data["rule_set"] == "request" and data["final_decision"] == "block"
    assert data["decision_source"] == "X1" and "120 USD" in data["reasons"][0]
    wrapped = client.post(
        "/rules/evaluate", json={"transaction": body(), "rules": {"rules": [BLOCK_RULE]}}
    )
    assert wrapped.json()["final_decision"] == "block"


def test_rules_evaluate_invalid_rule_set_is_422_with_readable_errors(client: TestClient) -> None:
    broken = {**BLOCK_RULE, "action": {"risk_boost": 5, "decision": "maybe", "flag": "x"}}
    response = client.post("/rules/evaluate", json={"transaction": body(), "rules": [broken]})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_rule_set"
    assert error["details"][0]["rule"] == "X1"
    assert any("action" in d["field"] for d in error["details"])

    unknown = {**BLOCK_RULE, "condition": {"feature": "no_such_column", "op": ">", "value": 1}}
    response = client.post("/rules/evaluate", json={"transaction": body(), "rules": [unknown]})
    assert response.status_code == 422
    assert "no_such_column" in json.dumps(response.json())


def test_rules_evaluate_bad_condition_errors_are_not_union_noise(client: TestClient) -> None:
    bad_op = {
        **BLOCK_RULE,
        "condition": {"all": [{"feature": "TransactionAmt", "op": "~", "value": 1}]},
    }
    response = client.post("/rules/evaluate", json={"transaction": body(), "rules": [bad_op]})
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert [d["field"] for d in details] == ["condition.all.0.op"]
    assert "Node" not in json.dumps(details)


# ---- /rag/query -------------------------------------------------------------------------------


def test_rag_query_answer_and_sources(client: TestClient, world: World) -> None:
    response = client.post(
        "/rag/query", json={"question": "R01 nedir?", "k": 3, "filters": {"rule_ids": ["R01"]}}
    )
    data = response.json()
    assert response.status_code == 200 and data["llm_status"] == "ok"
    assert data["answer"] and data["sources"][0]["chunk_id"] == "a#b"
    assert data["grounded"] is True and data["abstained"] is False
    assert world.rag.calls[0] == {"question": "R01 nedir?", "rule_ids": ["R01"], "k": 3}


def test_rag_query_validation(client: TestClient) -> None:
    assert client.post("/rag/query", json={"question": "a"}).status_code == 422
    assert client.post("/rag/query", json={"question": "geçerli soru", "k": 0}).status_code == 422
    bad = client.post("/rag/query", json={"question": "geçerli soru", "filters": {"x": 1}})
    assert bad.status_code == 422


def test_rag_query_ollama_down_keeps_sources_and_never_500(world: World) -> None:
    world.rag.text, world.rag.flags = None, ["llm_unavailable"]
    for client in make_client(world):
        data = client.post("/rag/query", json={"question": "R01 nedir?"}).json()
        assert data["answer"] is None and data["llm_status"] == "unavailable"
        assert data["sources"]


def test_rag_query_embedding_down_and_missing_index(world: World) -> None:
    world.rag.error = EmbeddingUnavailableError("down")
    for client in make_client(world):
        response = client.post("/rag/query", json={"question": "R01 nedir?"})
        assert response.status_code == 200 and response.json()["llm_status"] == "unavailable"
    world.rag.error = IndexNotBuiltError("run make rag-index")
    for client in make_client(world):
        response = client.post("/rag/query", json={"question": "R01 nedir?"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "rag_unavailable"


def test_rag_query_timeout() -> None:
    from tests.api.conftest import FakeRAG

    world = World(rag=FakeRAG(delay=1.0), llm_timeout=0.2)
    for client in make_client(world):
        data = client.post("/rag/query", json={"question": "R01 nedir?"}).json()
        assert data["llm_status"] == "timeout" and data["answer"] is None


# ---- /health and errors -----------------------------------------------------------------------


def test_health_ok(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["model_artifacts"]["ok"] is True
    assert data["model_artifacts"]["detail"]["rules_loaded"] >= 10
    assert data["ollama"]["ok"] is True and data["ollama"]["detail"]["models"]["bge-m3"] is True
    assert data["faiss_index"]["ok"] in (True, False)  # depends on a local make rag-index
    assert data["status"] in ("ok", "degraded")


def test_health_when_ollama_is_down_is_degraded_not_an_error(world: World) -> None:
    for client in make_client(world, ollama=down_client()):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ollama"]["ok"] is False and data["status"] == "degraded"
        assert client.post("/score", json=body()).status_code == 200  # /score is unaffected


def test_unknown_route_and_unhandled_error_use_the_json_envelope(world: World) -> None:
    def boom(txn: dict[str, Any]) -> Any:
        raise RuntimeError("secret internal detail")

    world.scorer.score = boom  # type: ignore[method-assign,assignment]
    for client in make_client(world):
        response = client.post("/score", json=body())
        assert response.status_code == 500
        error = response.json()["error"]
        assert error["code"] == "internal_error" and "secret" not in json.dumps(error)
        assert client.get("/nope").status_code == 404


def test_openapi_lists_all_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/score", "/explain", "/rules", "/rules/reload", "/rules/evaluate", "/rag/query"):
        assert path in paths
    assert "/health" in paths


def test_classify_llm_plan_without_explainer_is_skipped() -> None:
    from src.agents.messages import AgentResponse, PlanInfo
    from src.api.mappers import classify_llm

    plan = PlanInfo(source="llm", steps=["anomaly:score", "context:adjust", "rule:evaluate"])
    response = AgentResponse(correlation_id="c1", status="ok", plan=plan)
    assert classify_llm(response) == "skipped"
    assert classify_llm(response, "no answer within 60 s") == "timeout"


def test_explain_without_rag_index_returns_facts_and_trace(world: World) -> None:
    world.rag.error = IndexNotBuiltError("run make rag-index")
    for client in make_client(world):
        data = explain(client)
        assert data["llm_status"] == "unavailable" and data["narrative"] is None
        assert data["facts"]["decision"] == "allow" and data["trace"]
