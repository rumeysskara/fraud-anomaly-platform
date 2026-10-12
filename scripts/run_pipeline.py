"""Run the batch pipeline (Steps 1-7) in order: profile, features, score, context, rules.

The RAG index (`make rag-index`, needs Ollama), the agents demo and the API are separate."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import set_seed  # noqa: E402

# step name -> script
STEPS: dict[str, str] = {
    "profile": "scripts/run_profiling.py",
    "features": "scripts/build_features.py",
    "score": "scripts/run_scoring.py",
    "context": "scripts/run_context.py",
    "rules": "scripts/run_rules.py",
}
# Not part of `make pipeline`: needs a running Ollama (make rag-index) or is a demo/service.

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
            log.error("step %s: %s does not exist", name, script)
            return 2
        log.info("run %s", name)
        result = subprocess.run([sys.executable, str(path)], cwd=ROOT)
        if result.returncode != 0:
            log.error("step %s failed", name)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
