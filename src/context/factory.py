"""Factory: build a ContextAdjustEngine from saved artifacts (no training at request time)."""

from __future__ import annotations

from pathlib import Path

import joblib

from src.context.config import ContextConfig, load_context_config
from src.context.engine import ContextAdjustEngine
from src.context.params import ContextParams
from src.core.config import ROOT_DIR
from src.scoring.service import META_FILE


def params_directory(cfg: ContextConfig, sample: bool = False) -> Path:
    """Directory of context_params.json (configs/context.yaml paths.params_dir[/sample])."""
    base = ROOT_DIR / cfg.params_dir
    return base / "sample" if sample else base


def load_engine(
    detectors_dir: Path, params_dir: Path | None = None, cfg: ContextConfig | None = None
) -> ContextAdjustEngine:
    """Load config, learned params and the Step 5 weights + aggregate normalizer."""
    cfg = cfg or load_context_config()
    params = ContextParams.load(params_dir or params_directory(cfg))
    meta = joblib.load(detectors_dir / META_FILE)
    return ContextAdjustEngine(cfg, params, meta["weights"], meta["aggregate_normalizer"])
