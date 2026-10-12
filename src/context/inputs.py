"""Assemble the engine input for the batch path (features + raw fields + layer scores).

features.parquet has no ProductCD / addr2 / raw amount and no "e-mail seen before" flag, so they are
taken from merged.parquet by TransactionID. The online path receives the same fields in the record
(the e-mail flag comes from the entity store's e-mail set: email in the entity's previous e-mails).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.context.derive import EMAIL_KNOWN, FEATURE_COLUMNS, RAW_COLUMNS, layer_columns
from src.core.config import load_yaml
from src.features.utils import NA_KEY, entity_keys, value_keys

EMAIL_SOURCE = "P_emaildomain"
# entity key columns come from configs/entity.yaml (K-05), never hardcoded
RAW_SOURCE_COLUMNS = [
    "TransactionDT",
    *RAW_COLUMNS,
    *load_yaml("entity.yaml")["entity"]["columns"],
    EMAIL_SOURCE,
]


def email_known_batch(raw: pd.DataFrame, entity_columns: list[str] | None = None) -> pd.Series:
    """1 when the entity used this P_emaildomain in an EARLIER transaction, else 0.

    Rows are processed in (TransactionDT, TransactionID) order (raw is indexed by TransactionID),
    so of two rows with the same TransactionDT the smaller id is "earlier". The current and
    later rows are never counted. A missing e-mail is never "known".
    """
    cols = entity_columns or load_yaml("entity.yaml")["entity"]["columns"]
    order = np.lexsort((raw.index.to_numpy(), raw["TransactionDT"].to_numpy("int64")))
    sorted_raw = raw.iloc[order]
    email = value_keys(sorted_raw[EMAIL_SOURCE])
    key = entity_keys(sorted_raw, cols) + "\x1f" + email
    seen_before = key.groupby(key.to_numpy()).cumcount().to_numpy() >= 1
    known = seen_before & (email.to_numpy() != NA_KEY)
    out = pd.Series(known.astype("int8"), index=sorted_raw.index, name=EMAIL_KNOWN)
    return out.loc[raw.index]


def build_batch_inputs(
    features: pd.DataFrame,
    raw: pd.DataFrame,
    layer_scores: pd.DataFrame,
    weights: dict[str, float],
) -> pd.DataFrame:
    """Engine input indexed by TransactionID (all frames must share that index)."""
    raw = raw.loc[features.index]
    out = features[FEATURE_COLUMNS].copy()
    for col in RAW_COLUMNS:
        out[col] = raw[col]
    out[EMAIL_KNOWN] = email_known_batch(raw)
    lcols = layer_columns(weights)
    out[lcols] = layer_scores.loc[features.index, lcols]
    return out
