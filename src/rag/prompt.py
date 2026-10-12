"""Prompt builder: system instruction + retrieved passages (context) and the user message."""

from __future__ import annotations

import json
from typing import Any

from src.core.types import Chunk
from src.rag.config import PromptConfig


class PromptBuilder:
    """Builds the grounded prompt from the template in configs/rag.yaml."""

    def __init__(self, config: PromptConfig) -> None:
        self.config = config

    def build_context(self, chunks: list[Chunk]) -> str:
        """System text: instruction followed by the numbered passages."""
        cfg = self.config
        if chunks:
            passages = "\n\n".join(
                cfg.passage.format(
                    chunk_id=c.metadata["chunk_id"],
                    heading=" > ".join(c.metadata.get("heading_path", [])),
                    text=c.text,
                )
                for c in chunks
            )
        else:
            passages = cfg.no_context
        return f"{cfg.system}\n\n{cfg.context_header}\n{passages}"

    def build_user(self, question: str, explanation: dict[str, Any] | None = None) -> str:
        """User text: optional rule engine result, then the question."""
        cfg = self.config
        parts = []
        if explanation:
            shown = {k: explanation[k] for k in cfg.explanation_keys if k in explanation}
            body = json.dumps(shown, ensure_ascii=False, indent=2, default=str)
            parts.append(f"{cfg.explanation_header}\n{body}")
        parts.append(f"{cfg.question_header} {question}")
        if cfg.answer_reminder:
            parts.append(" ".join(cfg.answer_reminder.split()))
        return "\n\n".join(parts)
