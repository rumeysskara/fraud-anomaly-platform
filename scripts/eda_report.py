"""EDA report before Step 3: part A (label-free, all data) and part B (fit set only, labelled).

Usage: python scripts/eda_report.py   (SAMPLE_N works as in run_profiling.py)
Output: reports/eda/*.csv and *.png. The label is read only through src/evaluation: this script
takes X and y from the loader, slices the fit part and hands y to evaluation.fraud_rate_by.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.profiling.eda_figures as figs  # noqa: E402
from src.core.config import REPORTS_DIR, get_sample_n, load_settings, set_seed  # noqa: E402
from src.data.loader import add_datetime, load_merged  # noqa: E402
from src.evaluation.fraud_rate import fit_base_rate, fraud_rate_by  # noqa: E402
from src.profiling import eda  # noqa: E402

log = logging.getLogger(__name__)


def part_a(X: pd.DataFrame, ref_date: pd.Timestamp, out: Path) -> None:
    """Label-free tables and charts on all rows."""
    cfg = eda.eda_config()
    n = eda.top_n()
    specs = [
        ("ProductCD", None, "ProductCD"),
        ("card4", None, "card4 (kart ağı)"),
        ("card6", None, "card6 (kart tipi)"),
        ("P_emaildomain", n, "P_emaildomain (ilk 10)"),
        ("DeviceType", None, "DeviceType"),
    ]
    for col, top, label in specs:
        tbl = eda.value_share(X[col], top)
        tbl.to_csv(out / f"a_{col.lower()}.csv", index=False)
        figs.bar_share(
            tbl,
            "value",
            f"{label}: işlem sayısı ve payı (tüm veri)",
            "Tüm işlemler içindeki pay (%)",
            out / f"a_{col.lower()}.png",
        )

    dt = add_datetime(X)
    counts = eda.daily_counts(dt)
    counts.rename_axis("date").reset_index().to_csv(out / "a_daily_counts.csv", index=False)
    acf = eda.autocorrelation(counts)
    acf.to_csv(out / "a_acf.csv", index=False)
    figs.line_acf(
        acf,
        cfg["week_days"],
        f"Günlük işlem sayısının otokorelasyonu (lag {cfg['acf_min_lag']}-{cfg['acf_max_lag']})",
        out / "a_acf.png",
    )
    eda.weekday_profile(counts).to_csv(out / "a_weekday_profile.csv", index=False)

    day = (counts.index - ref_date).days
    windows, rows = [], []
    lo, hi = cfg["peak_window"]
    if day.max() >= hi + cfg["week_days"]:
        found = eda.best_peak_window(counts, ref_date)
        for name, (a, b) in (("istenen pencere", (lo, hi)), ("veride en yüksek pencere", found)):
            rows.append({"window": name, **eda.window_stats(counts, a, b, ref_date)})
            windows.append(
                (a, b, f"{name}: gün {a}-{b} ({rows[-1]['start_date']} - {rows[-1]['end_date']})")
            )
        pd.DataFrame(rows).to_csv(out / "a_peak_windows.csv", index=False)
    if day.max() >= cfg["spike_day"] + cfg["week_days"]:
        pd.DataFrame([eda.spike_stats(counts, ref_date)]).to_csv(out / "a_spike.csv", index=False)
        figs.daily_volume(
            counts,
            windows,
            cfg["spike_day"],
            ref_date,
            "Günlük işlem hacmi: Noel dönemi tepesi ve 92. gün sıçraması",
            out / "a_daily_volume.png",
        )
    amounts = eda.top_amounts(X["TransactionAmt"])
    amounts.to_csv(out / "a_top_amounts.csv", index=False)
    figs.bar_amounts(
        amounts, "En sık 20 TransactionAmt değeri ve payı (tüm veri)", out / "a_top_amounts.png"
    )


def part_b(Xf: pd.DataFrame, yf: pd.Series, ref_date: pd.Timestamp, out: Path) -> None:
    """Fit-only fraud-rate tables (descriptive). Groups are built label-free from Xf."""
    base = fit_base_rate(yf)
    pd.DataFrame([base]).to_csv(out / "b_base_rate.csv", index=False)
    dt = add_datetime(Xf)
    n = eda.top_n()
    d2_groups, d2_mode = eda.dominant_value_groups(Xf["addr2"])
    items = [
        ("productcd", "ProductCD", eda.category_groups(Xf["ProductCD"]), False),
        ("card4", "card4", eda.category_groups(Xf["card4"]), False),
        ("card6", "card6", eda.category_groups(Xf["card6"]), False),
        ("devicetype", "DeviceType", eda.category_groups(Xf["DeviceType"]), False),
        ("has_identity", "has_identity", eda.category_groups(Xf["has_identity"]), False),
        (
            "p_emaildomain",
            "P_emaildomain (ilk 10)",
            eda.category_groups(Xf["P_emaildomain"], n),
            False,
        ),
        ("hour", "Saat (referans tarihli datetime)", eda.hour_groups(dt), True),
        (
            "amount_decile",
            "TransactionAmt desili (sınırlar fit'ten)",
            eda.decile_groups(Xf["TransactionAmt"]),
            False,
        ),
        ("d1_zero", "D1 = 0 (yeni kart) ve diğerleri", eda.d1_zero_groups(Xf["D1"]), False),
        ("addr2", f"addr2 baskın değer ({d2_mode:g}) ve diğerleri", d2_groups, False),
        (
            "email_match",
            "P_emaildomain ve R_emaildomain eşleşmesi",
            eda.email_match_groups(Xf["P_emaildomain"], Xf["R_emaildomain"]),
            False,
        ),
    ]
    for key, label, groups, vertical in items:
        tbl = fraud_rate_by(yf, groups, eda.eda_config()["min_n_flag"])
        tbl.to_csv(out / f"b_{key}.csv", index=False)
        figs.bar_rate(
            tbl,
            "group",
            base["base_rate"],
            f"{label}: fraud oranı (yalnızca fit kümesi)",
            label,
            out / f"b_{key}.png",
            vertical=vertical,
        )


def main() -> int:
    """Run parts A and B and write csv + png under reports/eda/."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    set_seed()
    sample_n = get_sample_n()
    out = REPORTS_DIR / "eda" / ("sample" if sample_n else "")
    out.mkdir(parents=True, exist_ok=True)
    ref_date = pd.Timestamp(settings["time"]["reference_date"])

    X, y, _ = load_merged(sample_n=sample_n, settings=settings)
    cut = int(len(X) * settings["split"]["fit_ratio"])
    part_a(X, ref_date, out)
    # Part B: only the fit part (first fit_ratio rows by time) is passed on; holdout is not read.
    part_b(X.iloc[:cut], y.iloc[:cut], ref_date, out)
    log.info("EDA written to %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
