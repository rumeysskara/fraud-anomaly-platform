"""Small latency test against a running API (sequential requests, p50/p95).

    uvicorn src.api.main:app &                 # in another terminal
    python -m src.api.loadtest --score 200 --explain 6

Payloads are real holdout rows (no label is read) with fresh TransactionIDs and times after the
end of the data, so every /score call is a new transaction for an entity known from the snapshot.
/explain calls the local LLM; its latency is dominated by Ollama, not by this service.
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any

import httpx
import numpy as np
import pandas as pd

from src.api.consistency import _payload, api_columns
from src.core.config import PROCESSED_DIR, get_sample_n
from src.data.loader import split_by_time

FIRST_NEW_ID = 90_000_000
STEP_SECONDS = 30


def make_payloads(n: int, sample: bool) -> list[dict[str, Any]]:
    """n holdout rows with fresh ids and increasing times after the last known transaction."""
    path = PROCESSED_DIR / f"merged{'_sample' if sample else ''}.parquet"
    frame = pd.read_parquet(path, columns=api_columns(path))
    _, holdout = split_by_time(frame)
    last_dt = int(frame["TransactionDT"].max())
    rows = holdout.iloc[np.linspace(0, len(holdout) - 1, n).astype(int)]
    payloads = []
    for i, tid in enumerate(rows.index):
        payload = _payload(rows, int(tid))
        payload.update(TransactionID=FIRST_NEW_ID + i, TransactionDT=last_dt + 1 + i * STEP_SECONDS)
        payloads.append(payload)
    return payloads


def percentiles(values_ms: list[float]) -> dict[str, float]:
    """p50, p95 and max of a list of latencies."""
    ordered = sorted(values_ms)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {
        "n": len(ordered),
        "p50_ms": round(statistics.median(ordered), 1),
        "p95_ms": round(p95, 1),
        "max_ms": round(ordered[-1], 1),
    }


def measure(client: httpx.Client, path: str, bodies: list[dict[str, Any]]) -> dict[str, float]:
    """POST every body; return latency percentiles (wall clock, including HTTP)."""
    times = []
    for body in bodies:
        started = time.perf_counter()
        response = client.post(path, json=body)
        times.append((time.perf_counter() - started) * 1000)
        response.raise_for_status()
    return percentiles(times)


def main() -> None:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--score", type=int, default=200)
    parser.add_argument("--explain", type=int, default=6)
    args = parser.parse_args()
    payloads = make_payloads(args.score + args.explain, sample=get_sample_n() is not None)
    with httpx.Client(base_url=args.url, timeout=300) as client:
        print("/score", measure(client, "/score", payloads[: args.score]))
        explain_bodies = [{"transaction": p, "question": None} for p in payloads[args.score :]]
        if explain_bodies:
            print("/explain", measure(client, "/explain", explain_bodies))


if __name__ == "__main__":
    main()
