"""Generates the rule and context cards of the knowledge base from the config files (K-29).

Sources: configs/rules.yaml (+ the files it lists, e.g. rules_extra.json), configs/context.yaml and
the curated Turkish notes in knowledge_base/sources/rule_notes.yaml. The cards are regenerated on
every index build, so a changed rule can never leave a stale card behind. This module reads the
config files directly (no import of src/rules or src/context).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from src.core.config import CONFIG_DIR
from src.rag.config import RagSettings

logger = logging.getLogger(__name__)

NOTICE = (
    "Bu dosya {sources} dosyalarından otomatik üretildi (scripts/build_rag_index.py); "
    "elle düzenlemeyin, değişiklik için kaynak dosyayı düzenleyin."
)


def fmt_num(value: Any) -> str:
    """Number in Turkish style (decimal comma, no trailing zeros)."""
    if isinstance(value, bool):
        return "evet" if value else "hayır"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


def _signed(value: float) -> str:
    return f"{value:+.2f}".replace(".", ",")


class ConditionRenderer:
    """Turns the rule condition DSL into plain Turkish bullet lines."""

    def __init__(self, settings: RagSettings, params: dict[str, str]) -> None:
        self.labels = settings.feature_labels
        self.ops = settings.operator_labels
        self.params = params  # param name -> "441,95 (fit TransactionAmt q95)"

    def render(self, node: dict[str, Any], depth: int = 0, top: bool = True) -> list[str]:
        """Bullet lines for a condition node (all / any / not / leaf)."""
        if "all" in node:
            return self._group("Aşağıdakilerin TÜMÜ sağlanmalı:", node["all"], depth, top)
        if "any" in node:
            return self._group("Aşağıdakilerden EN AZ BİRİ sağlanmalı:", node["any"], depth, top)
        if "not" in node:
            return self._group("Şu koşul SAĞLANMAMALI:", [node["not"]], depth, top)
        return [f"{'  ' * depth}- {self._leaf(node)}"]

    def _group(self, title: str, children: list[dict], depth: int, top: bool) -> list[str]:
        if top:  # the root group is a paragraph; its children are the first-level bullets
            lines, child_depth = [title, ""], 0
        else:
            lines, child_depth = [f"{'  ' * depth}- {title}"], depth + 1
        for child in children:
            lines.extend(self.render(child, child_depth, top=False))
        return lines

    def _leaf(self, clause: dict[str, Any]) -> str:
        feature, op = clause["feature"], clause["op"]
        label = self.labels.get(feature, feature)
        head = f"{label} (`{feature}`)"
        word = self.ops.get(op, op)
        value = clause.get("value")
        if op in ("is_null", "isna", "notna"):
            empty = op != "notna" and value is not False
            return f"{head} {'boş' if empty else 'dolu'}"
        if op == "between":
            low, high = (self._value(v) for v in value)
            return f"{head} {low} ile {high} arasında (uçlar dahil)"
        return f"{head} {word} (`{op}`) {self._value(value)}"

    def _value(self, value: Any) -> str:
        if isinstance(value, dict) and "param" in value:
            name = value["param"]
            return f"{self.params.get(name, '?')} [`{name}`]"
        if isinstance(value, list):
            return ", ".join(self._value(v) for v in value)
        if isinstance(value, str):
            return f"`{value}`"
        return fmt_num(value)


def _quantile_text(q: float) -> str:
    return "q" + fmt_num(round(q * 100, 4))


def _rule_params(rules_cfg: dict[str, Any], root: Path) -> dict[str, str]:
    """Param name -> readable value for rules.yaml (learned block + external artifact)."""
    learned = rules_cfg.get("learned", {})
    out: dict[str, str] = {}
    for name, spec in (rules_cfg.get("learned_params") or {}).items():
        value = learned.get(name)
        how = f"fit {spec['column']} {_quantile_text(spec['quantile'])}"
        out[name] = f"{fmt_num(float(value))} ({how})" if value is not None else f"({how})"
    for name, spec in (rules_cfg.get("external_params") or {}).items():
        path = root / spec["dir"] / spec["file"]
        how = f"Adım 6 {spec['file']}"
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8")).get("values", {}).get(spec["key"])
            out[name] = f"{fmt_num(float(value))} ({how})" if value is not None else f"({how})"
        else:
            out[name] = f"({how})"
    return out


def _context_params(ctx_cfg: dict[str, Any], values: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, spec in (ctx_cfg.get("learned_params") or {}).items():
        how = f"fit {spec['column']} " + (
            _quantile_text(spec["quantile"]) if "quantile" in spec else "en sık değer"
        )
        value = values.get(name)
        out[name] = f"{fmt_num(float(value))} ({how})" if value is not None else f"({how})"
    return out


def load_rule_definitions(rules_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read rules.yaml and every rule file it lists (YAML or JSON); return (config, rules)."""
    config = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    rules = list(config.get("rules") or [])
    for name in config.get("files", {}).get("rules", []):
        if name == rules_path.name:
            continue
        path = rules_path.parent / name
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.suffix == ".json"
            else yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        rules.extend(data["rules"] if isinstance(data, dict) else data)
    return config, rules


def _table(rows: list[tuple[str, str]], header: tuple[str, str] = ("Alan", "Değer")) -> list[str]:
    lines = [f"| {header[0]} | {header[1]} |", "|---|---|"]
    lines.extend(f"| {k} | {v} |" for k, v in rows)
    return lines


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def build_rule_cards(settings: RagSettings, config_dir: Path = CONFIG_DIR) -> str:
    """Markdown for knowledge_base/generated/rule_cards.md (one section per rule R01-R12)."""
    root = settings.path(".")
    config, rules = load_rule_definitions(config_dir / "rules.yaml")
    notes = yaml.safe_load(settings.path(settings.paths.rule_notes).read_text(encoding="utf-8"))
    renderer = ConditionRenderer(settings, _rule_params(config, root))
    sources = ", ".join(f"configs/{n}" for n in config["files"]["rules"])

    out = [
        "---",
        "doc_type: rule_card",
        "generated: true",
        "---",
        "<!-- AUTO-GENERATED by src/rag/kb_builder.py. Do not edit by hand. -->",
        "",
        "# Kural Kartları (kural motoru, Adım 7)",
        "",
        "## Kural özeti",
        "",
        f"*{NOTICE.format(sources=sources)}*",
        "",
    ]
    summary = [
        f"| {r['id']} | {r['name']} | {r['action']['decision']} | {r['priority']} | "
        f"{r['severity']} | {_signed(r['action']['risk_boost'])} |"
        for r in rules
    ]
    out += [
        "| Kural | Ad | Karar | Öncelik | Önem | Risk artışı |",
        "|---|---|---|---|---|---|",
        *summary,
        "",
    ]
    out += ["## Çakışma çözümü (conflict resolution)", ""]
    out += _bullets(notes["conflict_resolution"]) + [""]
    for rule in rules:
        out += _rule_card(rule, renderer, notes["rules"].get(rule["id"], {})) + [""]
    return "\n".join(out)


def _rule_card(
    rule: dict[str, Any], renderer: ConditionRenderer, note: dict[str, Any]
) -> list[str]:
    action = rule["action"]
    rows = [
        ("Kural ID", rule["id"]),
        ("Ad", rule["name"]),
        ("Karar", action["decision"]),
        ("Öncelik", f"{rule['priority']} (1 = en yüksek)"),
        ("Önem", rule["severity"]),
        ("Risk artışı", _signed(action["risk_boost"])),
        ("Bayrak", action["flag"]),
        ("Etiketler", ", ".join(rule.get("tags", [])) or "-"),
        ("Aktif", fmt_num(bool(rule.get("enabled", True)))),
    ]
    if rule.get("cooldown"):
        minutes = fmt_num(rule["cooldown"]["window_seconds"] / 60)
        rows.append(("Cooldown", f"entity başına {minutes} dakikada en fazla bir kez"))
    lines = [f"## {rule['id']} - {rule['name']}", "", *_table(rows), ""]
    lines += ["**Koşul (düz Türkçe):**", "", *renderer.render(rule["condition"]), ""]
    lines += [f"**Tanım (config, İngilizce):** {' '.join(str(rule['description']).split())}", ""]
    if note.get("rationale"):
        lines += [f"**Gerekçe:** {' '.join(note['rationale'].split())}", ""]
    if note.get("limits"):
        lines += ["**Bilinen sınırlar:**", "", *_bullets(note["limits"])]
    return lines


def build_context_cards(settings: RagSettings, config_dir: Path = CONFIG_DIR) -> str:
    """Markdown for knowledge_base/generated/context_cards.md (C1-C9b and the G1 guard)."""
    ctx = yaml.safe_load((config_dir / "context.yaml").read_text(encoding="utf-8"))
    notes = yaml.safe_load(settings.path(settings.paths.rule_notes).read_text(encoding="utf-8"))
    params_path = settings.path(settings.paths.context_params)
    values = {}
    if params_path.exists():
        values = json.loads(params_path.read_text(encoding="utf-8")).get("values", {})
    renderer = ConditionRenderer(settings, _context_params(ctx, values))
    bounds = ctx["bounds"]

    out = [
        "---",
        "doc_type: context_card",
        "generated: true",
        "---",
        "<!-- AUTO-GENERATED by src/rag/kb_builder.py. Do not edit by hand. -->",
        "",
        "# Context Kuralları (skor düzeltme, Adım 6)",
        "",
        "## Context düzeltme özeti",
        "",
        f"*{NOTICE.format(sources='configs/context.yaml')}*",
        "",
        "| Kural | Ad | Tür | Etki |",
        "|---|---|---|---|",
    ]
    for rule in ctx["rules"]:
        out.append(f"| {rule['id']} | {rule['name']} | {rule['type']} | {_effect(rule)} |")
    guard = ctx["guard"]
    out.append(
        f"| {guard['id']} | {guard['name']} | guard | "
        f"toplam çarpan >= {fmt_num(guard['min_total'])} |"
    )
    out += [
        "",
        f"Toplam çarpan [{fmt_num(bounds['min_total'])}, {fmt_num(bounds['max_total'])}] "
        "aralığına kırpılır.",
        "",
    ]
    out += ["## Çarpanların birleşimi", ""] + _bullets(notes["context_notes"]) + [""]
    for rule in ctx["rules"]:
        out += _context_card(rule, renderer, notes["context"].get(rule["id"], {})) + [""]
    guard_rows = [
        ("Kural ID", guard["id"]),
        ("Ad", guard["name"]),
        ("Tür", "guard (koruma)"),
        ("Etki", f"toplam çarpan >= {fmt_num(guard['min_total'])}"),
    ]
    out += [f"## {guard['id']} - {guard['name']}", "", *_table(guard_rows), ""]
    out += ["**Koşul (düz Türkçe):**", "", *renderer.render(guard["condition"]), ""]
    guard_note = notes["context"]["G1"]
    rationale = guard_note.get("rationale") or guard["rationale"]
    out += [f"**Gerekçe:** {' '.join(rationale.split())}", ""]
    out += ["**Bilinen sınırlar:**", "", *_bullets(guard_note["limits"]), ""]
    return "\n".join(out)


def _effect(rule: dict[str, Any]) -> str:
    if rule["type"] == "multiplicative":
        return f"çarpan x{fmt_num(rule['factor'])}"
    return f"{rule['layer']} katman ağırlığı x{fmt_num(rule['weight_multiplier'])}"


def _context_card(
    rule: dict[str, Any], renderer: ConditionRenderer, note: dict[str, Any]
) -> list[str]:
    rows = [
        ("Kural ID", rule["id"]),
        ("Ad", rule["name"]),
        ("Tür", rule["type"]),
        ("Etki", _effect(rule)),
    ]
    if rule.get("exclusive_group"):
        rows.append(("Dışlayıcı grup", rule["exclusive_group"]))
    if rule.get("only_if_lowers"):
        rows.append(("Koşul", "yalnızca skoru düşürürse uygulanır"))
    lines = [f"## {rule['id']} - {rule['name']}", "", *_table(rows), ""]
    lines += ["**Koşul (düz Türkçe):**", "", *renderer.render(rule["condition"]), ""]
    lines += [f"**Tanım (config, İngilizce):** {' '.join(str(rule['description']).split())}", ""]
    rationale = note.get("rationale") or rule["rationale"]
    lines += [f"**Gerekçe:** {' '.join(str(rationale).split())}", ""]
    if note.get("limits"):
        lines += ["**Bilinen sınırlar:**", "", *_bullets(note["limits"])]
    return lines


def write_generated(settings: RagSettings, config_dir: Path = CONFIG_DIR) -> list[Path]:
    """Write both card files into the generated KB folder; return their paths."""
    target = settings.path(settings.paths.generated_dir)
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "rule_cards.md": build_rule_cards(settings, config_dir),
        "context_cards.md": build_context_cards(settings, config_dir),
    }
    paths = []
    for name, text in files.items():
        path = target / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    logger.info("generated %s", [p.name for p in paths])
    return paths
