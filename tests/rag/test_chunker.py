"""Chunker: one chunk per section, heading path kept, tables intact, cap only at structure."""

from __future__ import annotations

from src.rag.chunker import chunk_markdown, extract_rule_ids, slugify

DOC = """---
doc_type: typology
---
# Başlık

## Bir bölüm

Kısa paragraf.

İlgili kurallar: R01, C2

### Alt bölüm

| a | b |
|---|---|
| 1 | 2 |
| 3 | 4 |

## R02 - kural kartı

Metin.
"""


def chunk(text: str, max_tokens: int = 512) -> list:
    return chunk_markdown(text, "knowledge_base/x.md", max_tokens, 3.0)


def test_one_chunk_per_section_with_heading_path() -> None:
    chunks = chunk(DOC)
    paths = [c.metadata["heading_path"] for c in chunks]
    assert paths == [
        ["Başlık", "Bir bölüm"],
        ["Başlık", "Bir bölüm", "Alt bölüm"],
        ["Başlık", "R02 - kural kartı"],
    ]
    assert chunks[1].text.startswith("Başlık > Bir bölüm > Alt bölüm")
    assert all(c.metadata["doc_type"] == "typology" for c in chunks)
    assert chunks[0].metadata["source_path"] == "knowledge_base/x.md"


def test_rule_ids_from_heading_and_related_line() -> None:
    chunks = chunk(DOC)
    assert chunks[0].metadata["rule_ids"] == ["R01", "C2"]
    assert chunks[1].metadata["rule_ids"] == []
    assert chunks[2].metadata["rule_ids"] == ["R02"]
    assert extract_rule_ids(["C6a - foreign_country"], "") == ["C6a"]


def test_chunk_ids_are_unique_and_readable() -> None:
    doc = "# T\n\n## Aynı\n\na\n\n## Aynı\n\nb\n"
    ids = [c.metadata["chunk_id"] for c in chunk(doc)]
    assert ids == ["x#ayni", "x#ayni-2"]
    assert slugify("Kart Testi (şüphe)") == "kart-testi-suphe"


def test_table_is_never_split_even_when_over_the_cap() -> None:
    rows = "\n".join(f"| satır {i} | değer {i} |" for i in range(40))
    doc = f"# T\n\n## Tablo\n\nGiriş paragrafı.\n\n| a | b |\n|---|---|\n{rows}\n"
    chunks = chunk(doc, max_tokens=30)
    table_chunks = [c for c in chunks if "| satır 0 |" in c.text]
    assert len(table_chunks) == 1
    assert "| satır 39 |" in table_chunks[0].text  # whole table in one chunk
    assert all(c.metadata["heading_path"] == ["T", "Tablo"] for c in chunks)


def test_long_section_splits_at_paragraph_boundaries_only() -> None:
    paragraphs = [f"Paragraf {i} " + " ".join(["kelime"] * 30) for i in range(6)]
    doc = "# T\n\n## Uzun\n\n" + "\n\n".join(paragraphs) + "\n"
    chunks = chunk(doc, max_tokens=120)
    assert len(chunks) > 1
    assert [c.metadata["part"] for c in chunks] == list(range(1, len(chunks) + 1))
    assert chunks[0].metadata["chunk_id"].endswith(".p1")
    joined = "\n".join(c.text for c in chunks)
    for paragraph in paragraphs:  # every paragraph is intact inside exactly one chunk
        assert sum(paragraph in c.text for c in chunks) == 1
        assert paragraph in joined


def test_long_list_splits_between_items() -> None:
    items = "\n".join(f"- madde {i} " + "söz " * 25 for i in range(8))
    chunks = chunk(f"# T\n\n## Liste\n\n{items}\n", max_tokens=100)
    assert len(chunks) > 1
    for c in chunks:
        for line in c.text.splitlines():
            if line.startswith("- madde"):
                assert line.rstrip().endswith("söz")  # no item is cut in the middle


def test_html_comment_and_empty_sections_are_skipped() -> None:
    doc = "<!-- generated -->\n\n# Boş başlık\n\n## Dolu\n\nmetin\n"
    chunks = chunk(doc)
    assert [c.metadata["heading_path"] for c in chunks] == [["Boş başlık", "Dolu"]]
