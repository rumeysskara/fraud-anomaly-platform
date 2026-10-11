# ruff: noqa: E501
"""Feature catalog: every produced column is described here (name, group, formula, text)."""

from __future__ import annotations

import pandas as pd

# (name, group, formula, description). Velocity features use group "entity".
_STATIC: list[tuple[str, str, str, str]] = [
    (
        "hour",
        "temporal",
        "((ref + TransactionDT) // 3600) % 24",
        "Hour of day on the reference clock (assumed date base).",
    ),
    (
        "day_of_week",
        "temporal",
        "weekday of ref + TransactionDT (Mon=0)",
        "Day of week on the reference calendar.",
    ),
    (
        "is_weekend",
        "temporal",
        "day_of_week >= 5",
        "Weekend on the REFERENCE calendar (assumption, not local time).",
    ),
    ("day_index", "temporal", "TransactionDT // 86400", "Day number since the reference date."),
    (
        "is_low_volume_window",
        "temporal",
        "(hour - start) mod 24 < 6",
        "Hour falls in the 6 consecutive hours with the lowest fit volume.",
    ),
    (
        "local_hour_est",
        "temporal",
        "(hour - start) mod 24",
        "Estimated local hour, assuming the low-volume window is local 00-06.",
    ),
    (
        "is_business_hours",
        "temporal",
        "9 <= local_hour_est < 18 and local weekday < 5",
        "Estimated local business hours on a weekday.",
    ),
    (
        "is_holiday",
        "temporal",
        "date in configs/holidays.yaml",
        "US federal holiday (New Year, MLK, Presidents, Memorial, Christmas).",
    ),
    (
        "holiday_season",
        "temporal",
        "learned season start <= date <= end (fit volume ratio block)",
        "Year-end volume season learned from fit daily volume (K-10).",
    ),
    (
        "days_to_nearest_holiday",
        "temporal",
        "min |date - holiday|",
        "Absolute days to the nearest listed holiday.",
    ),
    (
        "is_first_seen",
        "entity",
        "ent_txn_count == 0",
        "Entity has no earlier transaction (history features use safe defaults).",
    ),
    (
        "ent_txn_count",
        "entity",
        "count of earlier txns of entity",
        "Past transaction count of the approximate card group (card1+addr1).",
    ),
    (
        "ent_avg_amt",
        "entity",
        "expanding mean, shift(1)",
        "Past mean amount; fit global mean when no history.",
    ),
    (
        "ent_std_amt",
        "entity",
        "expanding std (ddof=1), shift(1)",
        "Past amount std; fit global std when fewer than 2 past txns.",
    ),
    ("ent_max_amt", "entity", "expanding max, shift(1)", "Past max amount; 0 when no history."),
    (
        "amt_ratio_to_ent_avg",
        "entity",
        "TransactionAmt / ent_avg_amt",
        "Amount relative to the entity's past mean; 1 when no history.",
    ),
    (
        "amt_zscore_ent",
        "entity",
        "(amt - ent_avg) / max(ent_std, 1.0)",
        "Amount z-score against entity history; 0 with fewer than 2 past txns.",
    ),
    (
        "ent_age_days",
        "entity",
        "(TransactionDT - first_dt) / 86400",
        "Days since the entity's first transaction; 0 when first seen.",
    ),
    (
        "ent_unique_device",
        "entity",
        "distinct earlier DeviceInfo",
        "Distinct devices seen earlier for the entity.",
    ),
    (
        "ent_unique_email",
        "entity",
        "distinct earlier P_emaildomain",
        "Distinct purchaser email domains seen earlier.",
    ),
    (
        "time_since_last_txn",
        "entity",
        "TransactionDT - previous dt",
        "Seconds since the entity's previous transaction; -1 when first seen.",
    ),
    (
        "avg_inter_arrival",
        "entity",
        "(last_dt - first_dt) / (n_past - 1)",
        "Mean past inter-arrival seconds; -1 with fewer than 2 past txns.",
    ),
    ("card_age_days", "entity", "D1", "Card age: days since first use (D1 interpretation, K-05)."),
    ("is_new_card", "entity", "D1 == 0", "New card flag."),
    ("card_start_day", "entity", "TransactionDT // 86400 - D1", "D1n: card start day."),
    (
        "card_new_addr",
        "relational",
        "ent_txn_count == 0 and card1 seen before",
        "Known card1 used with a new addr1 (new entity of an old card).",
    ),
    (
        "device_ent_match",
        "relational",
        "earlier txns of entity with same DeviceInfo",
        "How often this device was used by the entity before; 0 when device missing.",
    ),
    (
        "has_recipient",
        "relational",
        "R_emaildomain notna",
        "Recipient email present (structural missingness, not an error).",
    ),
    (
        "email_mismatch",
        "relational",
        "P != R, both present",
        "Purchaser/recipient email domains differ; 0 unless both are present.",
    ),
    (
        "foreign_addr2",
        "relational",
        "addr2 notna and != fit mode",
        "Billing country differs from the most frequent fit value (foreign proxy).",
    ),
    (
        "addr2_missing",
        "relational",
        "addr2 isna",
        "addr2 missing (separate flag, also linked to 3-decimal amounts).",
    ),
    (
        "os_browser_rare",
        "relational",
        "fit share of (id_30,id_31) < 1e-4",
        "Rare or unseen OS/browser combination (only when id_30/id_31 present).",
    ),
    ("amt_log", "context", "log1p(TransactionAmt)", "Log amount."),
    (
        "amt_n_decimals",
        "context",
        "decimals of TransactionAmt (0-3)",
        "Number of decimals; 3 = possible currency conversion (community reading).",
    ),
    ("amt_has_3dec", "context", "amt_n_decimals == 3", "Three-decimal amount flag."),
    (
        "amt_fit_freq",
        "context",
        "share of fit rows with the same cent amount",
        "How common the exact amount is in the fit set; 0 if unseen.",
    ),
    (
        "amt_is_common",
        "context",
        "amount in fit top-20 amounts",
        "Fixed-price style amount (59, 117, ...).",
    ),
    (
        "amt_vs_product_q",
        "context",
        "ECDF of fit amounts within ProductCD",
        "Amount percentile within the ProductCD.",
    ),
    (
        "amt_dev_card4_card6",
        "context",
        "(log amt - group mean) / group std (fit)",
        "Log-amount deviation within card4+card6.",
    ),
    (
        "amt_dev_addr1",
        "context",
        "(log amt - group mean) / group std (fit)",
        "Log-amount deviation within the addr1 region (global stats for small groups).",
    ),
    ("has_identity", "context", "identity record exists", "Identity record present."),
    ("dist1_missing", "context", "dist1 isna", "dist1 missing."),
    ("dist2_missing", "context", "dist2 isna", "dist2 missing."),
    ("dist1_log", "context", "log1p(dist1)", "Distance signal 1 (NaN kept)."),
    ("dist2_log", "context", "log1p(dist2)", "Distance signal 2 (NaN kept)."),
]


def build_catalog(
    windows: list[str],
    freq_columns: list[str],
    passthrough_cols: list[str],
    model_input_exclude: dict[str, str] | None = None,
    small_window: str = "1h",
) -> pd.DataFrame:
    """Return the catalog in the exact output column order.

    `model_input` is True unless the feature is listed in model_input_exclude (name -> reason);
    excluded features stay in features.parquet but Step 4 must not feed them to models.
    """
    rows = list(_STATIC)
    pos = [r[0] for r in rows].index("avg_inter_arrival") + 1
    rows.insert(
        pos,
        (
            f"small_amt_streak_{small_window}",
            "entity",
            f"past txns in {small_window} with amt <= fit small-amount quantile",
            f"Card-testing signal: earlier small-amount txns in the last {small_window}.",
        ),
    )
    names = {r[0] for r in rows}
    vel = []
    for w in windows:
        vel.append(
            (
                f"ent_cnt_{w}",
                "entity",
                f"earlier txns in last {w}",
                f"Past transaction count in the last {w} (velocity).",
            )
        )
    for w in windows:
        vel.append(
            (
                f"ent_sum_{w}",
                "entity",
                f"sum of earlier amounts in last {w}",
                f"Past amount total in the last {w} (velocity).",
            )
        )
    rows += vel
    rows += [
        (
            f"freq_{c}",
            "context",
            f"fit share of {c} value",
            f"Frequency encoding of {c} (unseen = 0).",
        )
        for c in freq_columns
    ]
    rows += [
        (
            c,
            "passthrough",
            "raw value",
            "Raw C/D/V column (redundancy-cluster representative or unclustered).",
        )
        for c in passthrough_cols
    ]
    assert len(names) == len(_STATIC) + 1
    cat = pd.DataFrame(rows, columns=["name", "group", "formula", "description"])
    exclude = model_input_exclude or {}
    cat["model_input"] = ~cat["name"].isin(exclude)
    cat["model_input_note"] = cat["name"].map(exclude).fillna("")
    return cat
