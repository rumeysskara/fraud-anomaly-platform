"""Batch = online: 20 holdout transactions scored by the API code equal the batch output.

Uses the SAMPLE_N=50000 artifacts and reports (`SAMPLE_N=50000 make pipeline`), i.e. real data,
so it is marked `real_data` and excluded from `make test` (run: pytest -m real_data). It is also
skipped when the files are not there. The full-data version is `python -m src.api.consistency`.
Synthetic batch = online tests live in the lower layers (tests/features, tests/context, ...).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from src.api.consistency import ATOL, run_check, summarize
from src.api.main import create_app
from src.api.online import OnlineScorer
from src.container import Container
from src.core.config import ARTIFACTS_DIR, PROCESSED_DIR, REPORTS_DIR

NEEDED = [
    ARTIFACTS_DIR / "feature_pipeline_sample.joblib",
    ARTIFACTS_DIR / "detectors" / "sample" / "scoring_meta.joblib",
    PROCESSED_DIR / "merged_sample.parquet",
    PROCESSED_DIR / "features_sample.parquet",
    REPORTS_DIR / "rules" / "sample" / "rule_hits.parquet",
    REPORTS_DIR / "scores" / "sample" / "layer_scores.parquet",
]


def http_score_fn(scorer: OnlineScorer) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """POST /score on an app whose container serves `scorer` (schema validation included)."""
    container = Container()
    container.online_scorer.override(providers.Object(scorer))
    client = TestClient(create_app(container))

    def call(payload: dict[str, Any]) -> dict[str, Any]:
        response = client.post("/score", json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    return call


@pytest.mark.real_data
@pytest.mark.skipif(not all(p.exists() for p in NEEDED), reason="sample artifacts not built")
def test_twenty_holdout_transactions_match_the_batch_output() -> None:
    result = run_check(sample=True, n=20, spread=False, make_score_fn=http_score_fn)
    summary = summarize(result)
    assert summary["rows"] == 20
    assert summary["mismatching_rows"] == 0, result.to_string()
    assert summary["max_abs_diff"]["anomaly"] <= ATOL
    assert summary["max_abs_diff"]["final"] <= ATOL
