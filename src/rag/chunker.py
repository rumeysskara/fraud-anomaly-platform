"""Structure-aware markdown chunker (K-30).

The document is parsed with markdown-it-py. A chunk is the body of one heading section and keeps
its heading path. There is no fixed-size character cutting. Only when a section is longer than the
safety token cap is it split, and only at structure boundaries: between blocks (paragraph, list,
fence) or between the items of an over-long list. A table is never split.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from src.core.types import Chunk

RULE_ID = re.compile(r"\b[RCG]\d{1,2}[ab]?\b")
HEADING_RULE_ID = re.compile(r"^([RCG]\d{1,2}[ab]?)\b")
RELATED_RULES_LINE = re.compile(r"^\W*(?:İlgili|Ilgili) kurallar\W*[:：]\s*(.*)$", re.IGNORECASE)
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TURKISH_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


@dataclass
class _Block:
    """A top-level markdown block: its source text and, for lists, the item texts."""

    kind: str
    text: str
    items: list[str] = field(default_factory=list)


@dataclass
class _Section:
    """Heading path plus the blocks that follow it up to the next heading."""

    path: list[str]
    blocks: list[_Block] = field(default_factory=list)


def slugify(text: str) -> str:
    """Lowercase ASCII slug used in chunk ids ('R01 - card_testing' -> 'r01-card-testing')."""
    ascii_text = text.translate(TURKISH_ASCII).lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "section"


def estimate_tokens(text: str, chars_per_token: float) -> int:
    """Rough token estimate for the safety cap (not a tokenizer)."""
    return int(len(text) / chars_per_token) + 1


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Return (front matter dict, markdown body). A document may have no front matter."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    return (meta if isinstance(meta, dict) else {}), text[match.end() :]


def extract_rule_ids(heading_path: list[str], body: str) -> list[str]:
    """Rule ids of a section: the id in its own heading plus any 'İlgili kurallar:' lines."""
    ids: list[str] = []
    if heading_path:
        head = HEADING_RULE_ID.match(heading_path[-1])
        if head:
            ids.append(head.group(1))
    for line in body.splitlines():
        related = RELATED_RULES_LINE.match(line.strip())
        if related:
            ids.extend(RULE_ID.findall(related.group(1)))
    return list(dict.fromkeys(ids))


def _close_index(tokens: list[Token], start: int) -> int:
    """Index of the closing token that matches the level-0 opening token at `start`."""
    close_type = tokens[start].type.replace("_open", "_close")
    for j in range(start + 1, len(tokens)):
        if tokens[j].type == close_type and tokens[j].level == tokens[start].level:
            return j
    return len(tokens) - 1


def _list_items(tokens: list[Token], start: int, end: int, lines: list[str]) -> list[str]:
    """Source text of the direct items of the list spanning tokens[start:end]."""
    items = []
    for tok in tokens[start + 1 : end]:
        if tok.type == "list_item_open" and tok.level == tokens[start].level + 1 and tok.map:
            items.append("\n".join(lines[tok.map[0] : tok.map[1]]))
    return items


def _parse_sections(body: str) -> list[_Section]:
    """Walk the top-level tokens and group blocks under their heading path."""
    lines = body.splitlines()
    tokens = MarkdownIt("commonmark").enable("table").parse(body)
    sections = [_Section(path=[])]
    stack: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.level != 0 or tok.type.endswith("_close"):
            i += 1
            continue
        end = _close_index(tokens, i) if tok.nesting == 1 else i
        if tok.type == "heading_open":
            depth = int(tok.tag[1])
            stack = [*stack[: depth - 1], tokens[i + 1].content.strip()]
            sections.append(_Section(path=list(stack)))
        elif tok.map and tok.type != "html_block":  # html comments are provenance, not content
            text = "\n".join(lines[tok.map[0] : tok.map[1]]).rstrip()
            kind = tok.type.removesuffix("_open")
            items = []
            if kind in ("bullet_list", "ordered_list"):
                items = _list_items(tokens, i, end, lines)
            sections[-1].blocks.append(_Block(kind=kind, text=text, items=items))
        i = end + 1
    return [s for s in sections if s.blocks]


def _units(section: _Section, max_tokens: int, chars_per_token: float) -> list[str]:
    """Atomic pieces of a section: blocks, or list items when a list alone exceeds the cap."""
    units: list[str] = []
    for block in section.blocks:
        too_long = estimate_tokens(block.text, chars_per_token) > max_tokens
        if block.kind != "table" and too_long and block.items:
            units.extend(block.items)
        else:
            units.append(block.text)
    return units


def _pack(units: list[str], max_tokens: int, chars_per_token: float) -> list[str]:
    """Greedily join units into parts that stay under the cap (a single unit is never cut)."""
    parts: list[str] = []
    current: list[str] = []
    for unit in units:
        candidate = "\n\n".join([*current, unit])
        if current and estimate_tokens(candidate, chars_per_token) > max_tokens:
            parts.append("\n\n".join(current))
            current = [unit]
        else:
            current.append(unit)
    if current:
        parts.append("\n\n".join(current))
    return parts


def chunk_markdown(
    text: str,
    source_path: str,
    max_tokens: int,
    chars_per_token: float,
    default_doc_type: str = "other",
) -> list[Chunk]:
    """Split one markdown document into chunks with heading path and rule-id metadata."""
    meta, body = split_front_matter(text)
    doc_type = str(meta.get("doc_type", default_doc_type))
    stem = Path(source_path).stem
    seen: dict[str, int] = {}
    chunks: list[Chunk] = []
    for section in _parse_sections(body):
        parts = _pack(_units(section, max_tokens, chars_per_token), max_tokens, chars_per_token)
        base = f"{stem}#{slugify(section.path[-1] if section.path else 'intro')}"
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            base = f"{base}-{seen[base]}"
        rule_ids = extract_rule_ids(section.path, "\n\n".join(parts))
        for n, part in enumerate(parts, start=1):
            chunk_id = base if len(parts) == 1 else f"{base}.p{n}"
            heading = " > ".join(section.path)
            chunks.append(
                Chunk(
                    text=f"{heading}\n\n{part}" if heading else part,
                    source=source_path,
                    metadata={
                        "chunk_id": chunk_id,
                        "doc_type": doc_type,
                        "rule_ids": rule_ids,
                        "source_path": source_path,
                        "heading_path": list(section.path),
                        "part": n,
                        "n_parts": len(parts),
                    },
                )
            )
    return chunks
