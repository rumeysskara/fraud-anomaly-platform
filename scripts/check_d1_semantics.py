"""Test what D1 means (previous-transaction gap vs card age) on the chosen entity.

Usage: python scripts/check_d1_semantics.py   (SAMPLE_N works as in run_profiling.py)
Writes reports/profile/d1_semantics.csv and d1_semantics.md. Label-free; seed from settings.yaml.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import REPORTS_DIR, get_sample_n, load_settings, set_seed  # noqa: E402
from src.data.loader import load_merged  # noqa: E402
from src.profiling.d1_semantics import d1_semantics  # noqa: E402

log = logging.getLogger(__name__)


def main() -> int:
    """Compute the D1 semantics table and write csv + short markdown."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    set_seed()
    sample_n = get_sample_n()
    out_dir = REPORTS_DIR / "profile" / ("sample" if sample_n else "")
    out_dir.mkdir(parents=True, exist_ok=True)

    X, _, _ = load_merged(sample_n=sample_n, settings=settings)  # label is not used
    res = d1_semantics(X, settings["time"]["time_column"], settings["seed"])
    res.to_csv(out_dir / "d1_semantics.csv", index=False)
    lines = ["# D1 semantigi testi\n", "| metric | value | n_rows | note |", "|---|---|---|---|"]
    lines += [f"| {r.metric} | {r.value:.4f} | {r.n_rows} | {r.note} |" for r in res.itertuples()]
    (out_dir / "d1_semantics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("\n%s", res.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
