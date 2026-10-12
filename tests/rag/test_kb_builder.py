"""KB generation from the real config files: every rule has a card, cards follow config changes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.core.config import CONFIG_DIR
from src.rag.chunker import chunk_markdown
from src.rag.config import RagSettings, load_rag_settings
from src.rag.kb_builder import (
    ConditionRenderer,
    build_context_cards,
    build_rule_cards,
    fmt_num,
    write_generated,
)

RULE_IDS = [f"R{n:02d}" for n in range(1, 13)]
CONTEXT_IDS = ["C1", "C2", "C3", "C4", "C5", "C6a", "C6b", "C7", "C8", "C9a", "C9b", "G1"]


@pytest.fixture()
def settings() -> RagSettings:
    return load_rag_settings()


def chunks_of(text: str) -> list:
    return chunk_markdown(text, "knowledge_base/generated/x.md", 768, 3.0)


def test_each_rule_has_exactly_one_card_chunk(settings: RagSettings) -> None:
    chunks = chunks_of(build_rule_cards(settings))
    cards = {c.metadata["rule_ids"][0]: c for c in chunks if c.metadata["rule_ids"]}
    assert sorted(cards) == RULE_IDS
    assert all(
        c.metadata["doc_type"] == "rule_card" and c.metadata["n_parts"] == 1 for c in cards.values()
    )
    r03 = cards["R03"].text
    assert "Cooldown" in r03 and "60 dakika" in r03
    assert "441,95" in cards["R04"].text  # learned amount_high filled in plain text
    assert "Bilinen sınırlar" in cards["R04"].text


def test_context_cards_cover_all_rules_and_guard(settings: RagSettings) -> None:
    chunks = chunks_of(build_context_cards(settings))
    ids = {c.metadata["rule_ids"][0] for c in chunks if c.metadata["rule_ids"]}
    assert ids == set(CONTEXT_IDS)
    c5 = next(c for c in chunks if c.metadata["rule_ids"] == ["C5"])
    assert "x0,5" in c5.text and "yalnızca skoru düşürürse" in c5.text


def test_generated_files_carry_the_auto_generated_notice(
    settings: RagSettings, tmp_path: Path
) -> None:
    paths = write_generated(
        settings.model_copy(
            update={"paths": settings.paths.model_copy(update={"generated_dir": str(tmp_path)})}
        )
    )
    assert len(paths) == 2
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert (
            "AUTO-GENERATED" in text and "otomatik üretildi" in text and "elle düzenlemeyin" in text
        )


def test_card_follows_a_changed_rule(settings: RagSettings, tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, config_dir)
    rules = yaml.safe_load((config_dir / "rules.yaml").read_text(encoding="utf-8"))
    for rule in rules["rules"]:
        if rule["id"] == "R06":
            rule["action"]["risk_boost"] = 0.12
            rule["condition"]["all"][0]["value"] = 7
    (config_dir / "rules.yaml").write_text(
        yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8"
    )
    extra = json.loads((config_dir / "rules_extra.json").read_text(encoding="utf-8"))
    extra["rules"] = extra["rules"][:1]  # R12 removed
    (config_dir / "rules_extra.json").write_text(json.dumps(extra), encoding="utf-8")

    chunks = chunks_of(build_rule_cards(settings, config_dir))
    by_id = {c.metadata["rule_ids"][0]: c for c in chunks if c.metadata["rule_ids"]}
    assert "R12" not in by_id and "R11" in by_id
    assert "+0,12" in by_id["R06"].text and "büyük veya eşit (`>=`) 7" in by_id["R06"].text


def test_condition_renderer_handles_nested_nodes_and_params(settings: RagSettings) -> None:
    renderer = ConditionRenderer(settings, {"p": "10 (fit q50)"})
    node = {
        "all": [
            {"feature": "TransactionAmt", "op": ">=", "value": {"param": "p"}},
            {"any": [{"feature": "addr2", "op": "is_null", "value": True}]},
            {"not": {"feature": "is_weekend", "op": "==", "value": 1}},
            {"feature": "amt_zscore_ent", "op": "between", "value": [-2.0, 2.0]},
        ]
    }
    text = "\n".join(renderer.render(node))
    assert "10 (fit q50) [`p`]" in text
    assert "EN AZ BİRİ" in text and "SAĞLANMAMALI" in text
    assert "-2 ile 2 arasında" in text
    assert "boş" in text


def test_fmt_num_uses_decimal_comma() -> None:
    assert fmt_num(441.95) == "441,95"
    assert fmt_num(2.0) == "2"
    assert fmt_num(12) == "12"
