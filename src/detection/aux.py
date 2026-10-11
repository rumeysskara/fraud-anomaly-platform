"""Auxiliary detector inputs that are not columns of features.parquet.

features.parquet has neither the entity key nor the raw DeviceInfo value. Both are derived from the
raw record by the same function in batch (merged.parquet) and online (API payload).
"""

from __future__ import annotations

import pandas as pd

from src.core.config import load_yaml
from src.features.utils import entity_keys, get_col

ENTITY_KEY = "entity_key"
HAS_DEVICE = "has_device"
AUX_SOURCE_COLUMNS = ["card1", "addr1", "DeviceInfo"]


def build_aux(raw: pd.DataFrame) -> pd.DataFrame:
    """Return [entity_key, has_device] for raw records (columns card1, addr1, DeviceInfo).

    The entity key columns come from configs/entity.yaml (K-05).
    """
    columns = load_yaml("entity.yaml")["entity"]["columns"]
    out = pd.DataFrame(index=raw.index)
    out[ENTITY_KEY] = entity_keys(raw, columns)
    out[HAS_DEVICE] = get_col(raw, "DeviceInfo").notna().astype("int8")
    return out
