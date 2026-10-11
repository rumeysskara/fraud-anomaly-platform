"""Step 1-2: load + join, profile, entity proxy comparison.

Usage: SAMPLE_N=50000 python scripts/run_profiling.py   (omit SAMPLE_N for full data)
Sample runs write to reports/profile/sample and data/processed/merged_sample.parquet.
"""

from __future__ import annotations

import logging
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import (  # noqa: E402
    PROCESSED_DIR,
    REPORTS_DIR,
    get_sample_n,
    load_settings,
    set_seed,
)
from src.data.loader import load_merged  # noqa: E402
from src.evaluation.base_rate import label_base_rates  # noqa: E402
from src.profiling.report import run_profile  # noqa: E402

log = logging.getLogger(__name__)


def peak_rss_mb() -> float:
    """Peak resident set size of this process in MB (macOS reports bytes)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3


def main() -> int:
    """Run the profiling step and log duration and peak memory."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    set_seed()
    sample_n = get_sample_n()
    sample = "_sample" if sample_n else ""
    out_dir = REPORTS_DIR / "profile" / ("sample" if sample_n else "")
    fig_dir = REPORTS_DIR / "figures" / ("sample" if sample_n else "")
    t0 = time.time()

    X, y, stats = load_merged(sample_n=sample_n, settings=settings)
    log.info(
        "loaded %s rows x %s cols, %.0f MB in memory, peak RSS %.0f MB",
        len(X),
        X.shape[1],
        X.memory_usage(deep=True).sum() / 1e6,
        peak_rss_mb(),
    )
    log.info("join stats: %s", stats)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    X.to_parquet(PROCESSED_DIR / f"merged{sample}.parquet")
    log.info("merged parquet written, peak RSS %.0f MB", peak_rss_mb())

    run_profile(X, stats, out_dir, fig_dir, settings, seed=settings["seed"])
    # Label base rates come from src/evaluation (profiling never reads y); reporting only.
    rates = label_base_rates(y, settings["split"]["fit_ratio"])
    rates.to_csv(out_dir / "label_base_rate.csv", index=False)
    log.info("label base rates:\n%s", rates.to_string())
    log.info("DONE in %.1f s, peak RSS %.0f MB", time.time() - t0, peak_rss_mb())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
