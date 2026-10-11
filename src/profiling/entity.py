"""Entity proxy comparison. Label-free: isFraud is never read here.

Candidates and thresholds come from configs/profiling.yaml (`entity`). The chosen entity and the
D1n definition (name, D1 column, day_seconds) come from configs/entity.yaml only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.profiling.config import entity_definition, profiling_config


def entity_codes(
    df: pd.DataFrame, cols: list[str], na_level_cols: list[str] | None = None
) -> np.ndarray:
    """Integer entity id per row for the combination of cols; -1 where any part is NaN.

    Columns in na_level_cols treat NaN as one more level instead of making the row undefined.
    """
    undefined = np.zeros(len(df), dtype=bool)
    key = np.zeros(len(df), dtype="int64")
    for c in cols:
        codes, _ = pd.factorize(df[c])
        if c in (na_level_cols or []):
            codes = codes + 1
        undefined |= codes < 0
        key, _ = pd.factorize(key * (int(codes.max(initial=0)) + 1) + np.maximum(codes, 0))
    key = key.astype("int64")
    key[undefined] = -1
    return key


def _scope_stats(
    key: np.ndarray,
    log_amt: np.ndarray,
    dt: np.ndarray,
    holdout_seen: float | None,
    day_seconds: int,
) -> dict:
    """Entity statistics for one slice of rows. key is -1 for undefined rows."""
    defined = key >= 0
    n_rows, n_def = len(key), int(defined.sum())
    out: dict = {
        "n_rows": n_rows,
        "undefined_rows": n_rows - n_def,
        "undefined_ratio": (n_rows - n_def) / max(n_rows, 1),
    }
    if n_def == 0:
        return out
    k, a, t = key[defined], log_amt[defined], dt[defined]
    uniq, inv = np.unique(k, return_inverse=True)
    cnt = np.bincount(inv)
    single = cnt == 1
    out.update(
        n_entities=len(uniq),
        single_txn_entity_ratio=float(single.mean()),
        single_txn_row_share=float(single.sum() / n_def),
        txn_min=int(cnt.min()),
        txn_median=float(np.median(cnt)),
        txn_p75=float(np.percentile(cnt, 75)),
        txn_p90=float(np.percentile(cnt, 90)),
        txn_p99=float(np.percentile(cnt, 99)),
        txn_max=int(cnt.max()),
        repeat_row_share=float(1 - len(uniq) / n_def),  # rows with earlier history (time-sorted)
    )
    s1 = np.bincount(inv, weights=a)
    s2 = np.bincount(inv, weights=a * a)
    multi = cnt >= 2
    var = (s2[multi] - s1[multi] ** 2 / cnt[multi]) / (cnt[multi] - 1)
    std_within = np.sqrt(np.maximum(var, 0))
    glob = float(np.std(a)) or np.nan
    out["median_within_logamt_std"] = float(np.median(std_within)) if multi.any() else np.nan
    out["global_logamt_std"] = glob
    by_entity = pd.Series(t).groupby(inv)
    span = (by_entity.max() - by_entity.min()).to_numpy()[multi] / day_seconds
    out["median_span_days"] = float(np.median(span)) if multi.any() else np.nan
    if holdout_seen is not None:
        out["holdout_seen_ratio"] = holdout_seen
    return out


def first_use_day(df: pd.DataFrame, time_col: str, d_col: str, day_seconds: int) -> pd.Series:
    """D1n = floor(TransactionDT / day_seconds) - D1: approximate first-use day of a card.

    NaN where D1 is NaN. Built from D1 only (label-free).
    """
    day = np.floor(df[time_col].to_numpy(dtype="float64") / day_seconds)
    return pd.Series(day - df[d_col].to_numpy(dtype="float64"), index=df.index)


def resolve_candidates(cfg: dict) -> dict[str, dict]:
    """Candidates from profiling.yaml; `from_entity_yaml: true` takes the chosen entity."""
    chosen = entity_definition()
    out = {}
    for name, cand in cfg["candidates"].items():
        if cand.get("from_entity_yaml"):
            cand = {"columns": chosen["columns"], "na_level": chosen.get("na_level", [])}
        out[name] = cand
    return out


def build_work_frame(df: pd.DataFrame, time_col: str, cfg: dict) -> pd.DataFrame:
    """Small frame with only the columns candidates need, plus the derived D1n column."""
    start = entity_definition()["card_start_day"]
    needed = {c for cand in resolve_candidates(cfg).values() for c in cand["columns"]}
    needed -= {start["name"]}
    work = df[[c for c in needed if c in df.columns]].copy()
    if start["d_column"] in df.columns:
        work[start["name"]] = first_use_day(df, time_col, start["d_column"], start["day_seconds"])
    return work


def candidate_keys(work: pd.DataFrame, cfg: dict) -> dict[str, np.ndarray]:
    """Entity code array per candidate whose columns all exist in work."""
    keys = {}
    for name, cand in resolve_candidates(cfg).items():
        if all(c in work.columns for c in cand["columns"]):
            keys[name] = entity_codes(work, cand["columns"], cand.get("na_level"))
    return keys


def compare_candidates(
    df: pd.DataFrame,
    time_col: str,
    fit_ratio: float,
    cfg: dict | None = None,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Compare candidate proxies on the full data and on the fit set (first fit_ratio).

    df must be sorted by time. Returns (table, keys). holdout_seen_ratio (full scope) =
    share of defined holdout rows whose entity already appears in the fit set.
    """
    cfg = cfg or profiling_config("entity")
    work = build_work_frame(df, time_col, cfg)
    keys = candidate_keys(work, cfg)
    cut = int(len(df) * fit_ratio)
    day_seconds = entity_definition()["card_start_day"]["day_seconds"]
    cands = resolve_candidates(cfg)
    log_amt = np.log1p(df[cfg["amount_column"]].to_numpy(dtype="float64"))
    dt = df[time_col].to_numpy(dtype="float64")
    rows = []
    for name, key in keys.items():
        if not cands[name].get("table", True):
            continue
        fit_keys, hold_keys = key[:cut], key[cut:]
        hold_def = hold_keys[hold_keys >= 0]
        seen = (
            np.isin(hold_def, np.unique(fit_keys[fit_keys >= 0])).mean()
            if hold_def.size
            else np.nan
        )
        for scope, sl, extra in (
            ("full", slice(None), float(seen)),
            ("fit", slice(0, cut), None),
        ):
            row = {
                "candidate": name,
                "columns": "+".join(cands[name]["columns"]),
                "scope": scope,
            }
            row.update(_scope_stats(key[sl], log_amt[sl], dt[sl], extra, day_seconds))
            rows.append(row)
    return pd.DataFrame(rows), keys


def d1n_constancy(
    work: pd.DataFrame, keys: dict[str, np.ndarray], cfg: dict | None = None
) -> pd.DataFrame:
    """Check whether D1n stays constant inside an entity (tolerance in days from config).

    Rows with D1n defined only. For the base entity (e.g. H: card1+addr1, without D1n) each
    entity is classified by its D1n values: single (one value), jitter (several values, range
    <= tolerance) or multi (range > tolerance). The same is reported for every level in the
    config; a level that contains D1n is constant by construction. Output is long:
    one row per (entity_level, scope, group) with entity and transaction shares.
    """
    cfg = cfg or profiling_config("entity")
    chk = cfg["constancy"]
    tol = chk["tolerance_days"]
    d1n = work[entity_definition()["card_start_day"]["name"]]
    rows = []
    for level in chk["levels"]:
        key = keys[level]
        ok = (key >= 0) & d1n.notna().to_numpy()
        g = pd.DataFrame({"k": key[ok], "d": d1n.to_numpy()[ok]}).groupby("k")["d"]
        agg = g.agg(["size", "min", "max", "nunique"])
        agg["range"] = agg["max"] - agg["min"]
        group = np.where(
            agg["nunique"] == 1, "single", np.where(agg["range"] <= tol, "jitter", "multi")
        )
        for scope, mask in (("all", agg["size"] >= 1), ("multi_txn", agg["size"] >= 2)):
            sub, grp = agg[mask], pd.Series(group, index=agg.index)[mask]
            for name in ("single", "jitter", "multi"):
                sel = grp == name
                rows.append(
                    {
                        "entity_level": level,
                        "scope": scope,
                        "d1n_group": name,
                        "n_entities": int(sel.sum()),
                        "entity_share": float(sel.mean()) if len(sub) else np.nan,
                        "n_txn": int(sub.loc[sel, "size"].sum()),
                        "txn_share": float(sub.loc[sel, "size"].sum() / max(sub["size"].sum(), 1)),
                        "median_range_days": (
                            float(sub.loc[sel, "range"].median()) if sel.any() else np.nan
                        ),
                    }
                )
    return pd.DataFrame(rows)


def entity_sizes(key: np.ndarray) -> np.ndarray:
    """Transactions per entity (undefined rows excluded)."""
    return np.bincount(np.unique(key[key >= 0], return_inverse=True)[1])
