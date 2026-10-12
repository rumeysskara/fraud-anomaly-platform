"""Which fitted artifacts the container loads: the full-data set or the SAMPLE_N set.

`make pipeline` writes the full set; `SAMPLE_N=50000 make pipeline` writes `*_sample` files and
`sample/` folders. The container follows the same SAMPLE_N environment variable, so the API (and
the agent demo) start on whichever set was built.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.context.config import load_context_config
from src.context.factory import params_directory
from src.core.config import ARTIFACTS_DIR, REPORTS_DIR


@dataclass(frozen=True)
class ArtifactSet:
    """Paths of the fitted artifacts behind the online scorer."""

    sample: bool
    feature_pipeline: Path
    entity_profiles: Path
    detectors_dir: Path
    context_params_dir: Path
    rules_sample_dir: Path


def resolve_artifact_set(sample_n: int | None) -> ArtifactSet:
    """Full-data paths when sample_n is None, otherwise the SAMPLE_N paths."""
    sample = sample_n is not None
    sfx = "_sample" if sample else ""
    detectors = ARTIFACTS_DIR / "detectors"
    return ArtifactSet(
        sample=sample,
        feature_pipeline=ARTIFACTS_DIR / f"feature_pipeline{sfx}.joblib",
        entity_profiles=ARTIFACTS_DIR / f"entity_profiles{sfx}.parquet",
        detectors_dir=detectors / "sample" if sample else detectors,
        context_params_dir=params_directory(load_context_config(), sample),
        rules_sample_dir=REPORTS_DIR / "rules" / "sample",
    )
