"""Orchestrates all profiling tables, figures and the markdown summary."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from src.data.loader import add_datetime
from src.profiling import distributions, entity, figures, quality, relations, schema
from src.profiling.config import entity_definition, profiling_config

log = logging.getLogger(__name__)


def _md_table(df: pd.DataFrame, float_fmt: str = "{:.4g}") -> str:
    """Render a DataFrame as a markdown table (no tabulate dependency)."""
    head = "| " + " | ".join(map(str, df.columns)) + " |\n"
    sep = "|" + "---|" * len(df.columns) + "\n"
    body = ""
    for _, r in df.iterrows():
        cells = [float_fmt.format(v) if isinstance(v, float) else str(v) for v in r]
        body += "| " + " | ".join(cells) + " |\n"
    return head + sep + body


def _save(df: pd.DataFrame, out_dir: Path, name: str, csv: bool = False) -> None:
    df.to_parquet(out_dir / f"{name}.parquet", index=False)
    if csv:
        df.to_csv(out_dir / f"{name}.csv", index=False)


def run_profile(
    X: pd.DataFrame,
    join_stats: dict[str, int],
    out_dir: Path,
    fig_dir: Path,
    settings: dict,
    seed: int | None = None,
) -> dict:
    """Write all profile tables/figures for X (time-sorted, indexed by TransactionID).

    Label-free: no target is passed in. Descriptive tables (schema, missing, quality, temporal,
    entity table) use all rows. Statistics that later steps learn (outliers, distributions,
    top-N, rare combinations, Spearman/Cramer relations, redundancy clusters) use the fit set
    only (first fit_ratio rows by time).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = profiling_config()
    seed = settings["seed"] if seed is None else seed
    time_col = settings["time"]["time_column"]
    fit_ratio = settings["split"]["fit_ratio"]
    cut = int(len(X) * fit_ratio)
    Xf = X.iloc[:cut]  # fit set (view, no copy)

    log.info("schema")
    sch = schema.infer_schema(X, time_col=time_col, cfg=cfg["schema"])
    _save(sch, out_dir, "column_schema", csv=True)

    log.info("missing + quality")
    miss = quality.missing_table(X, sch)
    gmiss = quality.group_missing(miss, cfg["quality"])
    _save(miss, out_dir, "missing")
    _save(gmiss, out_dir, "group_missing", csv=True)
    qual = quality.quality_checks(X, sch, cfg["quality"])
    _save(qual, out_dir, "quality_checks", csv=True)

    log.info("outliers + distributions")
    is_num = [
        pd.api.types.is_numeric_dtype(X[c]) and not pd.api.types.is_bool_dtype(X[c])
        for c in sch["column"]
        if c in X.columns
    ]
    num_cols = [
        c for c, ok in zip([c for c in sch["column"] if c in X.columns], is_num, strict=True) if ok
    ]
    numeric = sch[(sch["column"].isin(num_cols)) & (sch["inferred_type"] == "numeric")]["column"]
    numeric = numeric.tolist()
    _save(distributions.outlier_table(Xf, numeric, cfg["outliers"]), out_dir, "outliers")
    _save(
        distributions.numeric_distributions(Xf, numeric, cfg["distributions"]),
        out_dir,
        "distributions",
    )
    cat_cols = sch[sch["inferred_type"].isin(["categorical", "flag"])]["column"]
    cat_cols = [c for c in cat_cols if c in X.columns and X[c].nunique() > 0]
    # Numeric low-unique V/C-style columns are excluded from top-N; string/coded ones are kept.
    top_cols = [
        c
        for c in cat_cols
        if not pd.api.types.is_numeric_dtype(X[c])
        or sch.set_index("column").loc[c, "type_source"] == "dictionary"
    ]
    _save(distributions.categorical_topn(Xf, top_cols), out_dir, "categorical_topn")

    log.info("rare categories")
    sets = [s for s in cfg["rare"]["key_sets"] if all(c in X.columns for c in s)]
    string_cols = [c for c in top_cols if not pd.api.types.is_numeric_dtype(X[c])]
    sets += [[c] for c in string_cols]
    detail, rsum = distributions.rare_combinations(Xf, sets, cfg["rare"])
    _save(detail, out_dir, "rare_categories")
    _save(rsum, out_dir, "rare_summary", csv=True)

    log.info("relations")
    sch_i = sch.set_index("column")
    sp_cols = [
        c
        for c in num_cols
        if sch_i.loc[c, "inferred_type"] in ("numeric", "flag", "categorical")
        and sch_i.loc[c, "type_source"] != "dictionary"
        and sch_i.loc[c, "n_unique"] > 1
    ]
    sp = relations.spearman_pairs(Xf, sp_cols, seed, cfg["relations"])
    cv_cols = [
        c
        for c in cat_cols
        if sch_i.loc[c, "n_unique"] <= cfg["relations"]["cramers_max_levels"]
        and (
            not pd.api.types.is_numeric_dtype(X[c])
            or pd.api.types.is_bool_dtype(X[c])
            or sch_i.loc[c, "type_source"] == "dictionary"
        )
    ]
    cv = relations.cramers_pairs(Xf, cv_cols, seed, cfg["relations"])
    rel = pd.concat([sp, cv], ignore_index=True)
    _save(rel, out_dir, "column_relations")
    clusters = relations.redundancy_clusters(rel, sch, cfg["relations"])
    _save(clusters, out_dir, "redundancy_clusters", csv=True)

    log.info("entity candidates")
    ent, keys = entity.compare_candidates(X, time_col, fit_ratio, cfg["entity"])
    _save(ent, out_dir, "entity_patterns", csv=True)
    work = entity.build_work_frame(X, time_col, cfg["entity"])
    constancy = pd.DataFrame()
    chk = cfg["entity"]["constancy"]
    if all(level in keys for level in chk["levels"]):
        constancy = entity.d1n_constancy(work, keys, cfg["entity"])
        _save(constancy, out_dir, "d1n_constancy", csv=True)
    del work

    log.info("temporal + figures")
    dt = add_datetime(X)
    temporal = pd.concat(
        [
            dt.dt.hour.value_counts()
            .sort_index()
            .rename_axis("key")
            .reset_index(name="count")
            .assign(grain="hour_of_day"),
            dt.dt.dayofweek.value_counts()
            .sort_index()
            .rename_axis("key")
            .reset_index(name="count")
            .assign(grain="day_of_week"),
        ],
        ignore_index=True,
    )
    temporal["ratio"] = temporal["count"] / len(X)
    _save(temporal, out_dir, "temporal")
    days = (X[time_col] // entity_definition()["card_start_day"]["day_seconds"]).astype("int32")
    fig = cfg["figures"]
    figures.plot_null_by_group(gmiss, fig_dir / "null_by_group.png", fig)
    figures.plot_amount_log(Xf[cfg["entity"]["amount_column"]], fig_dir / "amount_log.png", fig)
    figures.plot_hourly_volume(
        pd.Series(dt.dt.hour.to_numpy()),
        pd.Series(days.to_numpy()),
        fig_dir / "hourly_volume.png",
        fig,
    )
    sizes = {
        n: entity.entity_sizes(k)
        for n, k in keys.items()
        if cfg["entity"]["candidates"][n].get("table", True)
    }
    figures.plot_entity_counts(sizes, fig_dir / "entity_size_distribution.png", fig)

    result = {
        "schema": sch,
        "group_missing": gmiss,
        "quality": qual,
        "entity": ent,
        "constancy": constancy,
        "clusters": clusters,
        "rare_summary": rsum,
        "join_stats": join_stats,
    }
    (out_dir / "summary.md").write_text(_summary(result, len(X), X.shape[1]), encoding="utf-8")
    return result


def _summary(res: dict, n_rows: int, n_cols: int) -> str:
    """Short markdown summary of the main findings."""
    sch, ent = res["schema"], res["entity"]
    high = sch[sch["is_high_cardinality"]][["column", "inferred_type", "n_unique", "null_ratio"]]
    types = sch["inferred_type"].value_counts().rename_axis("type").reset_index(name="n")
    cols = [
        "candidate",
        "scope",
        "undefined_ratio",
        "n_entities",
        "single_txn_entity_ratio",
        "single_txn_row_share",
        "txn_median",
        "txn_p90",
        "txn_p99",
        "txn_max",
        "repeat_row_share",
        "holdout_seen_ratio",
    ]
    parts = [
        f"# Profil ozeti\n\nSatir: {n_rows}, kolon (has_identity dahil): {n_cols}\n",
        "## Join\n" + "\n".join(f"- {k}: {v}" for k, v in res["join_stats"].items()),
        "\n## Tip dagilimi\n" + _md_table(types),
        "\n## Yuksek cardinality\n" + _md_table(high),
        "\n## Grup bazli eksik veri\n" + _md_table(res["group_missing"]),
        "\n## Kalite bulgulari\n" + _md_table(res["quality"].head(60)),
        "\n## Entity adaylari\n" + _md_table(ent[[c for c in cols if c in ent.columns]]),
        "\n## D1n sabitlik kontrolu\n" + _md_table(res["constancy"]),
    ]
    return "\n".join(parts) + "\n"
