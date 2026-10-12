"""RAGService: grounded answer, llm_unavailable fallback, embedding error, rule id routing."""

from __future__ import annotations

import pytest

from src.rag.config import PromptConfig, RetrievalConfig
from src.rag.errors import EmbeddingUnavailableError
from src.rag.prompt import PromptBuilder
from src.rag.retriever import HybridRetriever
from src.rag.service import RAGService, triggered_rule_ids
from tests.rag.conftest import FakeEmbedder, FakeLLM

PROMPT = PromptConfig(
    system="SISTEM: yalnızca bağlamdan cevap ver.",
    context_header="BAĞLAM:",
    passage="[{chunk_id}] {heading}\n{text}",
    no_context="(yok)",
    explanation_header="İŞLEM:",
    question_header="SORU:",
    answer_reminder="Kaynakları yaz.",
    explanation_keys=["final_decision", "triggered_rules"],
)


def make_service(store, embedder: FakeEmbedder, llm: FakeLLM) -> RAGService:
    retriever = HybridRetriever(
        embedder, store, RetrievalConfig(k=3, metadata_quota=2, rule_filter_doc_types=["rule_card"])
    )
    return RAGService(retriever, llm, PromptBuilder(PROMPT))


def test_answer_has_sources_and_used_context(small_store) -> None:
    llm = FakeLLM(answer="Kart testi budur. [rc#r01]")
    result = make_service(small_store, FakeEmbedder(), llm).answer("kart testi nedir")
    assert result.answer == "Kart testi budur. [rc#r01]"
    assert result.flags == []
    assert result.cited_ids == ["rc#r01"]
    assert {s.chunk_id for s in result.sources} >= {"rc#r01"}
    assert len(result.used_context) == len(result.sources)
    assert all(s.heading.startswith("Doc > ") for s in result.sources)


def test_prompt_is_grounded_and_contains_passages_and_explanation(small_store) -> None:
    llm = FakeLLM()
    explanation = {"final_decision": "block", "triggered_rules": [{"id": "R01"}], "extra": "x"}
    make_service(small_store, FakeEmbedder(), llm).answer("neden block", explanation=explanation)
    assert llm.last_context.startswith("SISTEM:")
    assert "[rc#r01]" in llm.last_context  # triggered rule's card is in the context
    assert '"final_decision": "block"' in llm.last_prompt
    assert "extra" not in llm.last_prompt  # only configured keys are shown
    assert "SORU: neden block" in llm.last_prompt
    assert llm.last_prompt.endswith("Kaynakları yaz.")


def test_llm_unavailable_returns_retrieval_only(small_store) -> None:
    result = make_service(small_store, FakeEmbedder(), FakeLLM(down=True)).answer("kart testi")
    assert result.answer is None
    assert result.flags == ["llm_unavailable"]
    assert result.sources and result.used_context


def test_embedding_unavailable_raises_specific_error(small_store) -> None:
    broken = FakeEmbedder(fail=True)
    service = make_service(small_store, broken, FakeLLM())
    with pytest.raises(EmbeddingUnavailableError):
        service.answer("kart testi")


def test_rule_ids_come_from_explanation_or_argument() -> None:
    payload = {"triggered_rules": [{"id": "R04"}, {"id": "R06"}, "R04"]}
    assert triggered_rule_ids(payload) == ["R04", "R06"]
    assert triggered_rule_ids(None) == []


def test_empty_context_uses_placeholder() -> None:
    assert "(yok)" in PromptBuilder(PROMPT).build_context([])


def make_strict(store, llm: FakeLLM, threshold: float = 0.3) -> RAGService:
    retriever = HybridRetriever(
        FakeEmbedder(),
        store,
        RetrievalConfig(k=3, metadata_quota=2, rule_filter_doc_types=["rule_card"]),
    )
    return RAGService(
        retriever, llm, PromptBuilder(PROMPT), threshold, "Bilgi yok", "UYARI: kaynaksız"
    )


def test_off_topic_question_abstains_without_calling_llm(small_store) -> None:
    llm = FakeLLM()
    result = make_strict(small_store, llm).answer("zebra ejderha piyano")
    assert result.abstained and result.answer == "Bilgi yok" and result.sources == []
    assert llm.last_prompt == ""  # the LLM was never called


def test_metadata_boosted_cards_do_not_mask_abstain(small_store) -> None:
    llm = FakeLLM()
    result = make_strict(small_store, llm).answer("zebra ejderha piyano", rule_ids=["R01"])
    assert result.abstained and llm.last_prompt == ""


def test_on_topic_question_is_not_abstained(small_store) -> None:
    result = make_strict(small_store, FakeLLM("tamam [rc#r01]")).answer("kart testi küçük tutar")
    assert not result.abstained and result.top_score >= 0.3


def test_grounded_when_all_cited_ids_were_retrieved(small_store) -> None:
    result = make_strict(small_store, FakeLLM("evet [rc#r01]")).answer("kart testi küçük tutar")
    assert result.grounded and result.warning is None


def test_unknown_cited_id_marks_ungrounded_with_warning(small_store) -> None:
    result = make_strict(small_store, FakeLLM("evet [rc#r01] [uydurma#id]")).answer(
        "kart testi küçük tutar"
    )
    assert not result.grounded and result.answer.endswith("UYARI: kaynaksız")
    assert result.cited_ids == ["rc#r01"]


def test_no_citation_marks_ungrounded(small_store) -> None:
    result = make_strict(small_store, FakeLLM("kaynak yazmadı")).answer("kart testi küçük tutar")
    assert not result.grounded and "UYARI" in result.answer


def test_llm_own_abstain_is_not_a_warning(small_store) -> None:
    result = make_strict(small_store, FakeLLM("Bilgi yok.")).answer("kart testi küçük tutar")
    assert result.abstained and result.warning is None and not result.grounded
