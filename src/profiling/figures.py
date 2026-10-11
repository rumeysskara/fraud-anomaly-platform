"""PNG figures for the technical document (matplotlib, Agg backend)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.profiling.config import profiling_config  # noqa: E402


def _save(fig: plt.Figure, path: Path, dpi: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def plot_null_by_group(group_missing: pd.DataFrame, path: Path, cfg: dict | None = None) -> Path:
    """Mean null ratio per column group (with min-max range)."""
    g = group_missing.sort_values("mean_null_ratio", ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    err = [g["mean_null_ratio"] - g["min_null_ratio"], g["max_null_ratio"] - g["mean_null_ratio"]]
    ax.bar(g["group"], g["mean_null_ratio"], yerr=err, capsize=3, color="steelblue")
    ax.set_ylabel("null ratio (mean, min-max)")
    ax.set_title("Null ratio by column group")
    return _save(fig, path, (cfg or profiling_config("figures"))["dpi"])


def plot_amount_log(amount: pd.Series, path: Path, cfg: dict | None = None) -> Path:
    """Histogram of log1p(TransactionAmt)."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(
        np.log1p(amount.dropna().astype("float64")),
        bins=(cfg or profiling_config("figures"))["amount_bins"],
        color="darkorange",
    )
    ax.set_xlabel("log1p(TransactionAmt)")
    ax.set_ylabel("count")
    ax.set_title("Transaction amount (log scale)")
    return _save(fig, path, (cfg or profiling_config("figures"))["dpi"])


def plot_hourly_volume(
    hours: pd.Series, days: pd.Series, path: Path, cfg: dict | None = None
) -> Path:
    """Transactions per hour of day and per day (assumed reference date)."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    hc = hours.value_counts().sort_index()
    axes[0].bar(hc.index, hc.to_numpy(), color="seagreen")
    axes[0].set_xlabel("hour of day (reference-date assumption)")
    axes[0].set_ylabel("transactions")
    dc = days.value_counts().sort_index()
    axes[1].plot(dc.index, dc.to_numpy(), color="seagreen")
    axes[1].set_xlabel("day offset")
    axes[1].set_title("Daily volume")
    axes[0].set_title("Hourly volume")
    return _save(fig, path, (cfg or profiling_config("figures"))["dpi"])


def plot_entity_counts(counts: dict[str, np.ndarray], path: Path, cfg: dict | None = None) -> Path:
    """Log-log distribution of transactions per entity for each candidate proxy."""
    fig, ax = plt.subplots(figsize=(8, 5))
    for name, c in counts.items():
        vals, freq = np.unique(c, return_counts=True)
        ax.plot(vals, freq, marker=".", linestyle="none", label=name)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("transactions per entity")
    ax.set_ylabel("number of entities")
    ax.legend(fontsize=7)
    ax.set_title("Entity size distribution by candidate proxy (full data)")
    return _save(fig, path, (cfg or profiling_config("figures"))["dpi"])
