"""Run pipeline steps in order. Steps whose script does not exist yet are skipped."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import set_seed  # noqa: E402

# step name -> script (written by later steps)
STEPS: dict[str, str] = {
    "profile": "scripts/profile_data.py",
    "features": "scripts/build_features.py",
    "score": "scripts/score_anomalies.py",
    "context": "scripts/adjust_context.py",
    "rules": "scripts/apply_rules.py",
    "index": "scripts/build_index.py",
}

log = logging.getLogger("pipeline")


def main() -> int:
    """Run the selected steps; return a process exit code."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=list(STEPS), help="run a single step")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()

    for name, script in STEPS.items():
        if args.only and args.only != name:
            continue
        path = ROOT / script
        if not path.exists():
            log.info("skip %s: %s not written yet", name, script)
            continue
        log.info("run %s", name)
        result = subprocess.run([sys.executable, str(path)], cwd=ROOT)
        if result.returncode != 0:
            log.error("step %s failed", name)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
