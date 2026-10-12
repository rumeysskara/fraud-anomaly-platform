"""Real retrieval accuracy (needs Ollama + built index): run with `pytest -m ollama -s`."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from src.rag.config import load_rag_settings
from src.rag.embedder import OllamaEmbedder
from src.rag.retrieval_eval import abstain_rates, evaluate_retrieval
from src.rag.retriever import HybridRetriever
from src.rag.store import FaissVectorStore

QUESTIONS = yaml.safe_load(
    (Path(__file__).parent / "retrieval_questions.yaml").read_text(encoding="utf-8")
)
KS = (1, 3, 5)
MIN_HIT_AT_5 = 0.7  # fixed before the first real run; never relaxed after seeing results


@pytest.mark.ollama
def test_real_retrieval_hit_at_k() -> None:
    settings = load_rag_settings()
    index_file = settings.index_dir / "index.faiss"
    if not index_file.exists():
        pytest.skip("artifacts/rag index not built (run: make rag-index)")
    try:
        httpx.get(settings.embedding.host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama is not reachable")
    retriever = HybridRetriever(
        OllamaEmbedder(settings.embedding, httpx.Client(base_url=settings.embedding.host)),
        FaissVectorStore.load(settings.index_dir),
        settings.retrieval,
    )
    result = evaluate_retrieval(retriever, QUESTIONS, KS)
    for row in result["rows"]:
        print(
            f"rank={row['rank']} top={row['top_score']:.3f}  {row['question']}"
            f"  -> {row['retrieved'][:3]}"
        )
    rates = abstain_rates(result["rows"], settings.retrieval.abstain_threshold)
    print("abstain:", rates, "threshold:", settings.retrieval.abstain_threshold)
    print("hit@k:", {k: round(v, 2) for k, v in result["hit_at_k"].items()})
    assert result["hit_at_k"][5] >= MIN_HIT_AT_5
    assert rates["false_abstain"] == 0.0  # a valid question must never be refused
