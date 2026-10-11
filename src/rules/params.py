"""Rule thresholds: learned on the FIT set (quantiles) or read from another step's artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.core.config import ROOT_DIR
from src.rules.repository import RuleSettings

PARAMS_FILE = "rule_params.json"
LEARNED_MARKER = "# ---- learned on the fit set by scripts/run_rules.py (do not edit by hand) ----"


def fit_params(fit_df: pd.DataFrame, settings: RuleSettings) -> dict[str, Any]:
    """Learn every `learned_params` entry (a quantile of a column) from fit rows only."""
    values: dict[str, Any] = {}
    for name, spec in settings.learned_params.items():
        col = fit_df[spec["column"]].dropna().astype("float64")
        values[name] = round(float(np.quantile(col, spec["quantile"])), 6)
    values["n_fit"] = len(fit_df)
    return values


def external_params(settings: RuleSettings, sample: bool = False) -> dict[str, Any]:
    """Read `external_params` (e.g. Step 6 C4 history threshold) from their artifact files."""
    values: dict[str, Any] = {}
    for name, spec in settings.external_params.items():
        directory = ROOT_DIR / spec["dir"]
        path = (directory / "sample" if sample else directory) / spec["file"]
        if not path.exists():
            raise FileNotFoundError(f"{path} not found (needed for rule param {name!r})")
        data = json.loads(path.read_text())
        values[name] = data.get("values", data)[spec["key"]]
    return values


def load_params(
    settings: RuleSettings, sample: bool = False, sample_dir: Path | None = None
) -> dict[str, Any]:
    """All params: learned (config `learned:` block, or sample JSON) + external."""
    if sample:
        if sample_dir is None:
            raise ValueError("sample params need sample_dir")
        learned = json.loads((sample_dir / PARAMS_FILE).read_text())["learned"]
    else:
        learned = settings.learned
    missing = set(settings.learned_params) - set(learned)
    if missing:
        raise KeyError(f"learned rule params missing {sorted(missing)}; run scripts/run_rules.py")
    return {**learned, **external_params(settings, sample)}


def save_params_json(directory: Path, learned: dict[str, Any], external: dict[str, Any]) -> Path:
    """Write learned + external params as readable JSON (report / sample runs)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / PARAMS_FILE
    path.write_text(json.dumps({"learned": learned, "external": external}, indent=2))
    return path


def write_learned_block(config_path: Path, learned: dict[str, Any]) -> None:
    """Replace the `learned:` block at the end of rules.yaml; keep everything above the marker."""
    text = config_path.read_text(encoding="utf-8")
    head = text.split(LEARNED_MARKER)[0].rstrip("\n")
    body = yaml.safe_dump({"learned": learned}, sort_keys=False)
    config_path.write_text(f"{head}\n\n{LEARNED_MARKER}\n{body}", encoding="utf-8")
