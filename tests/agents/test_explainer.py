"""RAG query construction and the template fallback for empty explanations (K-39)."""

from __future__ import annotations

import pytest

from src.agents.explainer_agent import is_empty_answer, strip_task_sentences
from src.agents.messages import AnalystRequest
from src.rag.errors import EmbeddingUnavailableError, IndexNotBuiltError
from tests.agents.conftest import RECORD, FakeEngine, FakeRAG

TASK = "TransactionID 3519086 işlemini incele ve bir inceleme notu yaz."


def test_task_sentences_are_removed(settings) -> None:
    patterns = settings.explainer.task_patterns
    assert strip_task_sentences(TASK, patterns) == ""
    mixed = "R03 nedir? " + TASK
    assert strip_task_sentences(mixed, patterns) == "R03 nedir?"
    assert strip_task_sentences(None, patterns) == ""


def test_score_review_query_targets_threshold_layers_and_review_steps(make_system) -> None:
    system = make_system(engine=FakeEngine("review", [], source="score"))
    system.llm.answer = (
        '{"steps":[{"agent":"rule","intent":"evaluate"},{"agent":"explainer","intent":"explain"}]}'
    )
    system.coordinator.analyze(AnalystRequest(record=dict(RECORD), question=TASK))
    query = system.rag.calls[0]["question"]
    assert "inceleme eşiği" in query and "review adımları" in query
    assert "temporal" in query  # highest layer score of the fake scorer (0.9)
    assert "incele " not in query and "not yaz" not in query


def test_rule_decision_without_question_uses_default_question(make_system, settings) -> None:
    system = make_system(engine=FakeEngine("block", ["R01"]))
    system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert system.rag.calls[0]["question"] == settings.explainer.default_question
    assert system.rag.calls[0]["rule_ids"] == ["R01"]


@pytest.mark.parametrize("text", ["Kaynaklar: [a#b] [c#d]", "[a#b]", "", "  Kaynaklar:  "])
def test_empty_or_source_only_answer_uses_template(make_system, text: str) -> None:
    system = make_system(engine=FakeEngine("review", [], source="score"), rag=FakeRAG(text=text))
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    exp = response.explanation
    assert exp is not None and exp.origin == "template"
    assert exp.label == "destek bilgisi" and exp.affects_decision is False
    assert "Karar: review" in (exp.text or "") and "reason" in (exp.text or "")
    assert "temporal 0.90" in (exp.text or "") and "C3" in (exp.text or "")
    assert "explanation_fallback" in exp.flags and exp.grounded is False
    events = [t for t in response.trace if t.intent == "explanation_fallback"]
    assert len(events) == 1
    assert response.decision == "review" and response.status == "ok"


def test_real_answer_is_kept(make_system) -> None:
    system = make_system(rag=FakeRAG(text="R01 kart testi kuralıdır. [a#b]"))
    response = system.coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    assert response.explanation is not None and response.explanation.origin == "rag"
    assert not [t for t in response.trace if t.intent == "explanation_fallback"]


def test_llm_unavailable_answer_falls_back_to_template(make_system) -> None:
    class Down(FakeRAG):
        def answer(self, question, explanation=None, rule_ids=None):  # type: ignore[override]
            result = super().answer(question, explanation, rule_ids)
            return result.model_copy(update={"answer": None, "flags": ["llm_unavailable"]})

    response = make_system(rag=Down()).coordinator.analyze(AnalystRequest(record=dict(RECORD)))
    exp = response.explanation
    assert exp is not None and exp.origin == "template"
    assert exp.flags == ["llm_unavailable", "explanation_fallback"]


def test_is_empty_answer_helper(settings) -> None:
    pattern = settings.explainer.empty_sources_pattern
    assert is_empty_answer("Kaynaklar: [x#y]", pattern)
    assert not is_empty_answer("Kural tetiklendi. Kaynaklar: [x#y]", pattern)


@pytest.mark.parametrize(
    "error", [IndexNotBuiltError("run make rag-index"), EmbeddingUnavailableError("ollama down")]
)
def test_missing_index_or_embedding_falls_back_to_template(make_system, error: Exception) -> None:
    class NoRetrieval(FakeRAG):
        def answer(self, question, explanation=None, rule_ids=None):  # type: ignore[override]
            raise error

    response = make_system(rag=NoRetrieval()).coordinator.analyze(
        AnalystRequest(record=dict(RECORD))
    )
    exp = response.explanation
    assert exp is not None and exp.origin == "template" and exp.grounded is False
    assert exp.flags == ["rag_unavailable", "explanation_fallback"]
    assert "Karar:" in (exp.text or "") and response.decision is not None
    assert any(t.intent == "explanation_fallback" for t in response.trace)
