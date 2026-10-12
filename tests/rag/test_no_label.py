"""The fraud label is never referenced by the RAG layer, config or knowledge base."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABEL = "is" + "Fraud"  # split so this file does not match itself


def test_label_name_absent_from_rag_files() -> None:
    files = [
        *(ROOT / "src" / "rag").rglob("*.py"),
        *(ROOT / "knowledge_base").rglob("*"),
        ROOT / "configs" / "rag.yaml",
        ROOT / "scripts" / "build_rag_index.py",
    ]
    offenders = [str(f) for f in files if f.is_file() and LABEL in f.read_text(encoding="utf-8")]
    assert offenders == []
