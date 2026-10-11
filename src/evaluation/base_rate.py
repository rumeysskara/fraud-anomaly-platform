"""Label base rates of the fit and holdout sets (reporting only; never used for selection)."""

from __future__ import annotations

import pandas as pd


def label_base_rates(y: pd.Series, fit_ratio: float) -> pd.DataFrame:
    """Positive rate of the whole data, the fit set and the holdout set.

    y must be time-ordered (the order load_data returns): the first fit_ratio rows are fit,
    the rest holdout, the same split as split_by_time.
    """
    cut = int(len(y) * fit_ratio)
    parts = {"all": y, "fit": y.iloc[:cut], "holdout": y.iloc[cut:]}
    return pd.DataFrame(
        {
            "scope": list(parts),
            "n_rows": [len(v) for v in parts.values()],
            "n_positive": [int(v.sum()) for v in parts.values()],
            "base_rate": [float(v.mean()) if len(v) else float("nan") for v in parts.values()],
        }
    )
