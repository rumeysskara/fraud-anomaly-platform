"""Column relations: Spearman (numeric), Cramer's V (categorical), redundancy clusters."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.profiling.config import profiling_config


def _sample(df: pd.DataFrame, n: int | None, seed: int) -> pd.DataFrame:
    """Seeded random row sample (analysis speed only; not a train/test split)."""
    if n is None or len(df) <= n:
        return df
    return df.sample(n=n, random_state=seed)


def spearman_pairs(
    df: pd.DataFrame,
    cols: list[str],
    seed: int,
    cfg: dict | None = None,
) -> pd.DataFrame:
    """Spearman pairs with |rho| >= spearman_min_abs (config `relations`).

    Ranks are computed per column over its non-null rows, then Pearson on ranks with
    pairwise-complete rows (a standard approximation). Pairs with fewer than
    min_periods shared rows are dropped.
    """
    cfg = cfg or profiling_config("relations")
    min_abs, min_periods = cfg["spearman_min_abs"], cfg["spearman_min_periods"]
    ranks = _sample(df[cols], cfg["sample_rows"], seed).astype("float64").rank()
    corr = ranks.corr(min_periods=min_periods).to_numpy()
    i, j = np.triu_indices_from(corr, k=1)
    vals = corr[i, j]
    keep = np.abs(vals) >= min_abs  # NaN compares False
    names = np.array(cols)
    return pd.DataFrame(
        {
            "col_a": names[i[keep]],
            "col_b": names[j[keep]],
            "metric": "spearman",
            "value": vals[keep],
        }
    )


def cramers_v(a: pd.Series, b: pd.Series) -> float:
    """Bias-corrected Cramer's V on rows where both are non-null."""
    mask = a.notna() & b.notna()
    if mask.sum() < 2:
        return float("nan")
    table = pd.crosstab(a[mask], b[mask]).to_numpy().astype("float64")
    n = table.sum()
    r, k = table.shape
    if r < 2 or k < 2:
        return 0.0
    expected = table.sum(1, keepdims=True) @ table.sum(0, keepdims=True) / n
    chi2 = ((table - expected) ** 2 / np.where(expected == 0, 1, expected)).sum()
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
    r_c, k_c = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
    denom = min(k_c - 1, r_c - 1)
    return float(np.sqrt(phi2 / denom)) if denom > 0 else 0.0


def cramers_pairs(
    df: pd.DataFrame,
    cols: list[str],
    seed: int,
    cfg: dict | None = None,
) -> pd.DataFrame:
    """All column pairs with Cramer's V >= cramers_min (config `relations`)."""
    cfg = cfg or profiling_config("relations")
    min_value = cfg["cramers_min"]
    sub = _sample(df[cols], cfg["sample_rows"], seed)
    rows = []
    for x in range(len(cols)):
        for y in range(x + 1, len(cols)):
            v = cramers_v(sub[cols[x]], sub[cols[y]])
            if v >= min_value:
                rows.append({"col_a": cols[x], "col_b": cols[y], "metric": "cramers_v", "value": v})
    return pd.DataFrame(rows, columns=["col_a", "col_b", "metric", "value"])


def redundancy_clusters(
    pairs: pd.DataFrame,
    schema: pd.DataFrame,
    cfg: dict | None = None,
) -> pd.DataFrame:
    """Connected components of Spearman pairs with |rho| >= cluster_threshold in one group.

    The representative of a cluster is its column with the lowest null ratio (ties: name).
    Only clusters with 2+ columns are returned.
    """
    threshold = (cfg or profiling_config("relations"))["cluster_threshold"]
    group = schema.set_index("column")["group"]
    null = schema.set_index("column")["null_ratio"]
    strong = pairs[(pairs["metric"] == "spearman") & (pairs["value"].abs() >= threshold)]
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(strong["col_a"], strong["col_b"], strict=True):
        if group.get(a) == group.get(b):
            parent[find(a)] = find(b)
    members: dict[str, list[str]] = {}
    for c in list(parent):
        members.setdefault(find(c), []).append(c)
    rows = []
    for cid, cols in enumerate(sorted(members.values(), key=lambda m: sorted(m)[0])):
        rep = min(cols, key=lambda c: (null.get(c, 1.0), c))
        for c in sorted(cols):
            rows.append(
                {
                    "cluster_id": cid,
                    "column": c,
                    "group": group.get(c),
                    "cluster_size": len(cols),
                    "representative": rep,
                }
            )
    return pd.DataFrame(
        rows, columns=["cluster_id", "column", "group", "cluster_size", "representative"]
    )
