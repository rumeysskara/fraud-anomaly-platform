"""FeaturePipeline: fit on the fit set, transform in batch, transform_one for the API.

Batch and online paths share the row-wise code (rowwise.py, timecal.py). History features
have two implementations of the same definition (history.batch_history vs EntityStore).
The label is never read here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.core.config import CONFIG_DIR, ROOT_DIR, load_settings, load_yaml
from src.features.catalog import build_catalog
from src.features.history import EntityStore, batch_history
from src.features.learned import LearnedStats, fit_stats
from src.features.rowwise import row_features
from src.features.timecal import CalendarSpec
from src.features.utils import (
    NA_KEY,
    amount_array,
    entity_keys,
    get_col,
    to_python,
    value_keys,
)

TIME_COL = "TransactionDT"
NUMERIC_INPUTS = {
    "TransactionDT",
    "TransactionAmt",
    "card1",
    "addr1",
    "addr2",
    "dist1",
    "dist2",
    "D1",
}


def finalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Memory control: bool -> int8, ints -> smallest int, floats -> float32."""
    for col in df.columns:
        kind = df[col].dtype.kind
        if kind == "b":
            df[col] = df[col].astype("int8")
        elif kind in "iu":
            df[col] = pd.to_numeric(df[col], downcast="integer")
        elif kind == "f":
            df[col] = df[col].astype("float32")
    return df


class FeaturePipeline:
    """Temporal, entity/velocity, relational and context features (past-only history)."""

    def __init__(
        self,
        config: dict[str, Any],
        calendar: CalendarSpec,
        entity_columns: list[str],
        stats: LearnedStats | None = None,
        store: EntityStore | None = None,
    ) -> None:
        self.config = config
        self.calendar = calendar
        self.entity_columns = entity_columns
        self.stats = stats
        self.store = store

    @classmethod
    def from_config(cls, config_dir: Path = CONFIG_DIR) -> FeaturePipeline:
        """Build an unfitted pipeline from configs/entity.yaml, holidays.yaml and settings.yaml."""
        entity = load_yaml("entity.yaml", config_dir)
        feats = entity["features"]
        hol = load_yaml(feats["holidays"]["file"], config_dir)["holidays"]
        cal = CalendarSpec.from_config(
            load_settings(config_dir)["time"]["reference_date"], feats, [h["date"] for h in hol]
        )
        return cls(feats, cal, list(entity["entity"]["columns"]))

    # ---- fit ----
    def fit(self, df: pd.DataFrame, clusters: pd.DataFrame | None = None) -> FeaturePipeline:
        """Learn fit statistics from the fit frame (first 80% by time)."""
        if clusters is None:
            path = ROOT_DIR / self.config["passthrough"]["clusters_file"]
            clusters = pd.read_csv(path) if path.exists() else None
        self.stats = fit_stats(df, self.config, self.calendar, clusters)
        self._names_cache = None
        return self

    @property
    def catalog(self) -> pd.DataFrame:
        """Feature catalog (name, group, formula, description) in output order."""
        L = self._need_stats()
        return build_catalog(
            list(self.config["windows"]),
            self.config["freq_columns"],
            L.passthrough_cols,
            self.config.get("model_input_exclude", {}),
            self.config["small_amount"]["window"],
        )

    @property
    def model_input_columns(self) -> list[str]:
        """Feature names Step 4 may use as model input (catalog.model_input is True)."""
        cat = self.catalog
        return list(cat.loc[cat["model_input"], "name"])

    def _names(self) -> list[str]:
        """Output column names (cached; the catalog is fixed once fitted)."""
        if getattr(self, "_names_cache", None) is None:
            self._names_cache = list(self.catalog["name"])
        return self._names_cache

    def _need_stats(self) -> LearnedStats:
        if self.stats is None:
            raise RuntimeError("FeaturePipeline is not fitted")
        return self.stats

    def _passthrough(self, df: pd.DataFrame) -> pd.DataFrame:
        """Raw representative V/C/D columns as float32 (NaN when the input lacks a column)."""
        cols = {c: get_col(df, c) for c in self._need_stats().passthrough_cols}
        return pd.DataFrame(cols, index=df.index).astype("float32")

    # ---- batch ----
    def _history_inputs(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        h = self.config["history"]
        return {
            "ent": entity_keys(df, self.entity_columns).to_numpy(dtype=object),
            "card": value_keys(get_col(df, "card1")).to_numpy(dtype=object),
            "dev": value_keys(get_col(df, h["device_column"])).to_numpy(dtype=object),
            "email": value_keys(get_col(df, h["email_column"])).to_numpy(dtype=object),
            "dt": df[TIME_COL].to_numpy("int64"),
            "amt": amount_array(df),
        }

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Features for many rows. History uses ONLY earlier rows of `df` in time order."""
        L = self._need_stats()
        dt = df[TIME_COL].to_numpy("int64")
        perm = np.argsort(dt, kind="stable")
        work = df.iloc[perm].reset_index(drop=True)
        rows = row_features(work, L, self.config, self.calendar)
        hist = batch_history(L=L, cfg=self.config, **self._history_inputs(work))
        parts = [rows, hist]
        if L.passthrough_cols:
            parts.append(self._passthrough(work))
        out = pd.concat(parts, axis=1)[self._names()]
        out.index = df.index[perm]
        out = out.iloc[np.argsort(perm, kind="stable")]  # back to the caller's order
        return finalize_dtypes(out)

    # ---- online ----
    def _frame_from_txn(self, txn: dict[str, Any]) -> pd.DataFrame:
        numeric = NUMERIC_INPUTS | set(self._need_stats().passthrough_cols)
        row = {k: (np.nan if v is None else v) for k, v in txn.items()}
        frame = pd.DataFrame([row])
        for col in numeric & set(frame.columns):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame

    def transform_one(self, txn: dict[str, Any], update: bool = False) -> dict[str, Any]:
        """Features of a single transaction dict, from the entity store (no training).

        update=True also appends the transaction to the store (stream replay / tests);
        the API path uses update=False.
        """
        L = self._need_stats()
        if self.store is None:
            self.store = EntityStore(L, self.config)
        frame = self._frame_from_txn(txn)
        rows = row_features(frame, L, self.config, self.calendar)
        inp = self._history_inputs(frame)
        args = (inp["ent"][0], inp["card"][0], inp["dev"][0], inp["email"][0])
        dt, amt = int(inp["dt"][0]), float(inp["amt"][0])
        hist = pd.DataFrame([self.store.features(*args, dt, amt)])
        parts = [rows, hist]
        if L.passthrough_cols:
            parts.append(self._passthrough(frame))
        out = finalize_dtypes(pd.concat(parts, axis=1)[self._names()])
        if update:
            self.store.update(*args, dt, amt)
        return {k: to_python(v) for k, v in out.iloc[0].items()}

    def build_store(self, df: pd.DataFrame) -> EntityStore:
        """Replay `df` in time order into a fresh EntityStore (state after the last row)."""
        L = self._need_stats()
        work = df.iloc[np.argsort(df[TIME_COL].to_numpy("int64"), kind="stable")]
        inp = self._history_inputs(work)
        store = EntityStore(L, self.config)
        for ent, card, dev, email, dt, amt in zip(
            inp["ent"], inp["card"], inp["dev"], inp["email"], inp["dt"], inp["amt"], strict=True
        ):
            store.update(ent, card, dev, email, int(dt), float(amt))
        self.store = store
        return store

    # ---- persistence ----
    def save(self, path: Path) -> None:
        """Save the fitted pipeline (without the entity store) with joblib."""
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "config": self.config,
                "calendar": self.calendar,
                "entity_columns": self.entity_columns,
                "stats": self.stats,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path, store_path: Path | None = None) -> FeaturePipeline:
        """Load a saved pipeline; optionally attach the entity store parquet."""
        d = joblib.load(path)
        pipe = cls(d["config"], d["calendar"], d["entity_columns"], d["stats"])
        if store_path is not None and Path(store_path).exists():
            pipe.store = EntityStore.from_frame(
                pd.read_parquet(store_path), d["stats"], d["config"]
            )
        return pipe


__all__ = ["FeaturePipeline", "finalize_dtypes", "NA_KEY"]
