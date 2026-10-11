"""EDA charts: every chart has a title, labelled axes and direct value labels (PNG)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BLUE, ORANGE, GREY, RED = "#2f6690", "#d1873a", "#b8b8b8", "#b23a48"  # colour-blind friendly
DPI = 130
FONT = 10


def _style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=FONT)
    ax.xaxis.label.set_size(FONT + 1)
    ax.yaxis.label.set_size(FONT + 1)


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def bar_share(df: pd.DataFrame, label_col: str, title: str, xlabel: str, path: Path) -> Path:
    """Horizontal bars of row share per value, labelled with count and percent."""
    d = df.iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(d) + 1.6))
    ax.barh(d[label_col].astype(str), d["share"] * 100, color=BLUE)
    for y, (n, s) in enumerate(zip(d["n"], d["share"], strict=True)):
        ax.text(s * 100, y, f"  {n:,} ({s:.1%})", va="center", fontsize=FONT - 1)
    ax.set_xlim(0, d["share"].max() * 100 * 1.3)
    ax.set_title(title, fontsize=FONT + 3, loc="left")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Değer")
    _style(ax)
    return _save(fig, path)


def bar_rate(
    df: pd.DataFrame,
    label_col: str,
    base_rate: float,
    title: str,
    xlabel: str,
    path: Path,
    vertical: bool = False,
) -> Path:
    """Fraud-rate bars with 95% Wilson whiskers; small-n bars are grey and hatched."""
    d = df if vertical else df.iloc[::-1]
    pos = np.arange(len(d))
    rate = d["fraud_rate"].to_numpy() * 100
    err = np.vstack([rate - d["ci_low"].to_numpy() * 100, d["ci_high"].to_numpy() * 100 - rate])
    colors = [GREY if s else BLUE for s in d["small_n"]]
    hatch = ["//" if s else "" for s in d["small_n"]]
    labels = d[label_col].astype(str).to_numpy()
    if vertical:
        fig, ax = plt.subplots(figsize=(max(8, 0.4 * len(d) + 3), 4.8))
        bars = ax.bar(pos, rate, yerr=err, color=colors, capsize=2, error_kw={"lw": 1})
        ax.axhline(base_rate * 100, color=ORANGE, ls="--", lw=1.5)
        ax.set_xticks(
            pos, labels, rotation=45 if len(d) > 30 else 0, ha="right" if len(d) > 30 else "center"
        )
        ax.set_ylabel("Fraud oranı (%)")
        ax.set_xlabel(xlabel)
        ax.text(
            0.01,
            base_rate * 100,
            f"fit taban oranı {base_rate:.2%}",
            color=ORANGE,
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="bottom",
            fontsize=FONT - 1,
        )
    else:
        fig, ax = plt.subplots(figsize=(8.5, 0.5 * len(d) + 1.8))
        bars = ax.barh(pos, rate, xerr=err, color=colors, capsize=2, error_kw={"lw": 1})
        ax.axvline(
            base_rate * 100, color=ORANGE, ls="--", lw=1.5, label=f"fit taban oranı {base_rate:.2%}"
        )
        ax.set_yticks(pos, labels)
        ax.set_xlabel("Fraud oranı (%)  |  çubuk ucu: %95 Wilson aralığı")
        ax.legend(frameon=False, loc="lower right", fontsize=FONT - 1)
        ax.set_ylabel(xlabel)
        for y, n, r, hi, small in zip(
            pos, d["n"], rate, d["ci_high"] * 100, d["small_n"], strict=True
        ):
            ax.text(
                hi,
                y,
                f"  n={n:,}{' (küçük n)' if small else ''}  {r:.2f}%",
                va="center",
                fontsize=FONT - 1,
            )
        ax.set_xlim(0, float((d["ci_high"] * 100).max()) * 1.45)
    for b, h in zip(bars, hatch, strict=True):
        b.set_hatch(h)
    ax.set_title(title, fontsize=FONT + 3, loc="left")
    _style(ax)
    return _save(fig, path)


def line_acf(acf: pd.DataFrame, highlight_lag: int, title: str, path: Path) -> Path:
    """Autocorrelation by lag (raw and detrended); the highlighted lag is marked."""
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.plot(acf["lag"], acf["acf_raw"], marker="o", color=BLUE, label="ham seri")
    ax.plot(
        acf["lag"],
        acf["acf_detrended"],
        marker="s",
        color=ORANGE,
        label="7 günlük ortalama çıkarılmış",
    )
    row = acf[acf["lag"] == highlight_lag].iloc[0]
    for col, color in (("acf_raw", BLUE), ("acf_detrended", ORANGE)):
        ax.scatter(
            [highlight_lag], [row[col]], s=160, facecolors="none", edgecolors=RED, lw=2, zorder=5
        )
        ax.annotate(
            f"lag {highlight_lag}: {row[col]:.2f}",
            (highlight_lag, row[col]),
            xytext=(8, 8),
            textcoords="offset points",
            color=color,
            fontsize=FONT,
        )
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(acf["lag"])
    ax.set_xlabel("Gecikme (gün)")
    ax.set_ylabel("Otokorelasyon")
    ax.set_title(title, fontsize=FONT + 3, loc="left")
    ax.legend(frameon=False, fontsize=FONT - 1)
    _style(ax)
    return _save(fig, path)


def daily_volume(
    counts: pd.Series,
    windows: list[tuple[int, int, str]],
    spike_day: int,
    ref_date: pd.Timestamp,
    title: str,
    path: Path,
) -> Path:
    """Daily transaction count with highlighted windows (day offsets) and the spike day."""
    day = (counts.index - ref_date).days
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.plot(day, counts.to_numpy(), color=BLUE, lw=1.4)
    for (lo, hi, label), color in zip(windows, (ORANGE, "#6a994e"), strict=False):
        ax.axvspan(lo - 0.5, hi + 0.5, color=color, alpha=0.2, label=label)
    sd = counts[day == spike_day]
    ax.scatter(
        [spike_day],
        sd.to_numpy(),
        color=RED,
        zorder=5,
        s=50,
        label=f"{spike_day}. gün ({sd.index[0].date()}): {int(sd.iloc[0]):,}",
    )
    ax.set_xlabel(f"Gün (referans {ref_date.date()} + gün ofseti)")
    ax.set_ylabel("Günlük işlem sayısı")
    ax.set_title(title, fontsize=FONT + 3, loc="left")
    ax.legend(frameon=False, fontsize=FONT - 1)
    _style(ax)
    return _save(fig, path)


def bar_amounts(df: pd.DataFrame, title: str, path: Path) -> Path:
    """Most frequent TransactionAmt values (x = amount, y = row share)."""
    fig, ax = plt.subplots(figsize=(10, 4.8))
    pos = np.arange(len(df))
    ax.bar(pos, df["share"] * 100, color=BLUE)
    for x, s in enumerate(df["share"]):
        ax.text(x, s * 100, f"{s:.1%}", ha="center", va="bottom", fontsize=FONT - 2)
    ax.set_xticks(pos, [f"{a:g}" for a in df["amount"]], rotation=60, ha="right")
    ax.set_xlabel("TransactionAmt değeri (en sık 20)")
    ax.set_ylabel("Tüm işlemlerdeki pay (%)")
    ax.set_title(title, fontsize=FONT + 3, loc="left")
    _style(ax)
    return _save(fig, path)
