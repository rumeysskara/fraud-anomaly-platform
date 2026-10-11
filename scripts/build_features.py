"""Step 3: fit the feature pipeline on the fit set, transform all rows, save artifacts.

Usage: SAMPLE_N=50000 python scripts/build_features.py   (omit SAMPLE_N for full data)
Reads data/processed/merged[_sample].parquet (written by Step 1-2); falls back to the loader.
Sample runs write *_sample outputs and do not touch configs/entity.yaml.
The label is not read: merged.parquet has no label column.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import (  # noqa: E402
    ARTIFACTS_DIR,
    CONFIG_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    get_sample_n,
    set_seed,
)
from src.data.loader import load_merged, split_by_time  # noqa: E402
from src.features.config_io import write_learned_block  # noqa: E402
from src.features.pipeline import FeaturePipeline  # noqa: E402
from src.features.reports import (  # noqa: E402
    feature_summary,
    holiday_volume_check,
    season_detection_table,
    season_threshold_sensitivity,
)
from src.features.timecal import detect_season  # noqa: E402

log = logging.getLogger(__name__)


def main() -> int:
    """Run Step 3 end to end."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    sample_n = get_sample_n()
    sfx = "_sample" if sample_n else ""
    t0 = time.time()

    path = PROCESSED_DIR / f"merged{sfx}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
    else:
        df, _, _ = load_merged(sample_n=sample_n)
    log.info("loaded %s rows x %s cols", *df.shape)

    fit, _ = split_by_time(df)
    pipe = FeaturePipeline.from_config().fit(fit)
    stats = pipe.stats
    log.info("learned: %s", stats.as_config_block())

    feats = pipe.transform(df)
    log.info(
        "features %s x %s, %.0f MB, %.0fs",
        *feats.shape,
        feats.memory_usage().sum() / 1e6,
        time.time() - t0,
    )
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(PROCESSED_DIR / f"features{sfx}.parquet")

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    store = pipe.build_store(df)  # state after the last row = history for online scoring
    store.to_frame().to_parquet(ARTIFACTS_DIR / f"entity_profiles{sfx}.parquet")
    pipe.save(ARTIFACTS_DIR / f"feature_pipeline{sfx}.joblib")

    out = REPORTS_DIR / "features" / ("sample" if sample_n else "")
    out.mkdir(parents=True, exist_ok=True)
    catalog = pipe.catalog
    catalog.to_parquet(out / "feature_catalog.parquet")
    catalog.to_csv(out / "feature_catalog.csv", index=False)
    feature_summary(feats, catalog).to_csv(out / "feature_summary.csv", index=False)
    fit_dt = fit["TransactionDT"].to_numpy("int64")
    season_cfg = pipe.config["holidays"]["season"]
    holiday_volume_check(
        fit_dt, pipe.calendar, stats.season_days, tuple(season_cfg["compare_fixed"])
    ).to_csv(out / "holiday_volume_fit.csv", index=False)
    _, daily = detect_season(fit_dt, pipe.calendar.ref_seconds, season_cfg)
    season_detection_table(daily).to_csv(out / "season_detection_fit.csv", index=False)
    season_threshold_sensitivity(fit_dt, pipe.calendar.ref_seconds, season_cfg).to_csv(
        out / "season_threshold_sensitivity.csv", index=False
    )
    pd.DataFrame({"hour": range(24), "fit_rows": stats.hourly_counts}).to_csv(
        out / "hourly_volume_fit.csv", index=False
    )
    weekend_diff = float((feats["is_weekend"] != _local_weekend(df, stats, pipe)).mean())
    pd.DataFrame([{"share_rows_weekend_ref_ne_local": weekend_diff}]).to_csv(
        out / "weekend_ref_vs_local.csv", index=False
    )

    if not sample_n:
        write_learned_block(CONFIG_DIR / "entity.yaml", stats.as_config_block())
        if (
            stats.season
        ):  # visible copy next to the holiday list (the pipeline reads its fitted stats)
            write_learned_block(
                CONFIG_DIR / "holidays.yaml",
                {k: v for k, v in stats.as_config_block().items() if k.startswith("season")},
                key="learned_season",
            )
    log.info("done in %.0fs; entities in store: %s", time.time() - t0, len(store.entities))
    return 0


def _local_weekend(df: pd.DataFrame, stats, pipe: FeaturePipeline) -> pd.Series:
    """Weekend flag on the estimated LOCAL calendar (note only; is_weekend is reference-based)."""
    t = pipe.calendar.ref_seconds + df["TransactionDT"].to_numpy("int64")
    t = t + stats.local_offset_hours * 3600
    local_dow = ((t // 86400) + 3) % 7
    return pd.Series((local_dow >= 5).astype("int8"), index=df.index)


if __name__ == "__main__":
    raise SystemExit(main())
