"""Step 8: generate the rule cards, chunk the knowledge base, embed it and save the FAISS index.

Usage: python scripts/build_rag_index.py [--question "..."] [--no-llm]
Needs a running Ollama with the embedding model (bge-m3). The sample query at the end also uses
the LLM when it is available; otherwise the retrieval-only result is printed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.container import create_container  # noqa: E402
from src.rag.errors import EmbeddingUnavailableError  # noqa: E402
from src.rag.indexer import build_chunks, build_index  # noqa: E402
from src.rag.kb_builder import write_generated  # noqa: E402

logger = logging.getLogger("build_rag_index")

DEFAULT_QUESTION = "Kart testi şüphesi hangi koşulda tetiklenir ve analist ne yapmalı?"


def main() -> int:
    """Build the index and run one sample question."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM answer")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    container = create_container()
    settings = container.rag_settings()
    for path in write_generated(settings):
        logger.info("generated %s", path.relative_to(settings.path(".")))
    chunks = build_chunks(settings)
    logger.info("%d chunks from %d documents", len(chunks), len({c.source for c in chunks}))

    try:
        store = build_index(settings, container.embedder())
    except EmbeddingUnavailableError as exc:
        logger.error("cannot build the index: %s", exc)
        return 1
    logger.info("index saved to %s (%d vectors)", settings.index_dir, len(store))

    # The index is saved now, so the container can load it; the service carries the configured
    # abstain threshold and warnings (same object as the API).
    if args.no_llm:
        for chunk in container.retriever().retrieve(args.question):
            print(f"{chunk.score:.3f}  {chunk.metadata['chunk_id']}")
        return 0
    result = container.rag_service().answer(args.question)
    print(json.dumps(result.model_dump(exclude={"used_context"}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
