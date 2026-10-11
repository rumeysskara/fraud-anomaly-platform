"""Write fit-learned values into configs/entity.yaml so they are visible next to the settings."""

from __future__ import annotations

from pathlib import Path

import yaml

MARKER = "# ---- learned on the fit set by scripts/build_features.py (do not edit by hand) ----"


def write_learned_block(path: Path, block: dict, key: str = "learned") -> None:
    """Replace (or append) the `<key>:` block at the end of the YAML file; keep comments above."""
    text = path.read_text(encoding="utf-8")
    head = text.split(MARKER)[0].rstrip("\n")
    body = yaml.safe_dump({key: block}, sort_keys=False)
    path.write_text(f"{head}\n\n{MARKER}\n{body}", encoding="utf-8")
