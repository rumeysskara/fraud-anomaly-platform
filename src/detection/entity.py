"""Entity anomaly layer: deviation from the entity's own history with soft shrinkage (K-14).

score = w * entity_score + (1 - w) * global_score, w = n / (n + k), n = past transactions of the
entity (ent_txn_count, used ONLY here). The first transaction has w = 0. All parts are in
-log10(p) units; the layer is then quantile-normalized like the other layers.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.detection.aux import HAS_DEVICE
from src.detection.base import LayerDetector
from src.detection.tails import TailScorer

RATIO_FLOOR = 1e-6


def _num(df: pd.DataFrame, col: str) -> np.ndarray:
    """Column as float64 (absent column = NaN)."""
    if col not in df.columns:
        return np.full(len(df), np.nan)
    return df[col].to_numpy(dtype="float64", na_value=np.nan)


class EntityDetector(LayerDetector):
    """Amount-vs-history and new-device signals, blended with population signals."""

    name = "entity"

    def __init__(self, shrinkage_k: float, count_column: str, grid_points: int) -> None:
        super().__init__(grid_points)
        self.k = float(shrinkage_k)
        self.count_column = count_column
        self.global_std_ = 1.0
        self.scorers: dict[str, TailScorer] = {}
        self.min_freq_ = 1.0

    def _signals(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        """Raw entity-side quantities: amount z (global std when std = 0), log ratio, new device."""
        n = _num(df, self.count_column)
        amt = np.expm1(_num(df, "amt_log"))
        std = _num(df, "ent_std_amt")
        std_eff = np.where(std > 0, std, self.global_std_)
        has_hist = n >= 1
        z = np.where(has_hist, (amt - _num(df, "ent_avg_amt")) / std_eff, np.nan)
        ratio = np.maximum(_num(df, "amt_ratio_to_ent_avg"), RATIO_FLOOR)
        log_ratio = np.where(has_hist, np.log(ratio), np.nan)
        has_dev = _num(df, HAS_DEVICE) == 1
        new_dev = np.where(has_hist & has_dev, (_num(df, "device_ent_match") == 0) * 1.0, np.nan)
        return {"amount_z": z, "amount_ratio": log_ratio, "new_device": new_dev}

    def _fit_stats(self, df: pd.DataFrame) -> None:
        """Learn the global amount std and the fit distributions of every signal."""
        amt = np.expm1(_num(df, "amt_log"))
        self.global_std_ = float(np.nanstd(amt)) or 1.0
        self.min_freq_ = 1.0 / (len(df) + 1)
        sig = self._signals(df)
        self.scorers = {
            "amount_z": TailScorer("two", "zero").fit(sig["amount_z"]),
            "amount_ratio": TailScorer("two", "zero").fit(sig["amount_ratio"]),
            "new_device": TailScorer("discrete", "zero").fit(sig["new_device"]),
            "global_amount": TailScorer("two", "zero").fit(_num(df, "amt_log")),
            "global_new_addr": TailScorer("discrete", "zero").fit(_num(df, "card_new_addr")),
        }

    def parts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Entity score, global score, weight w and blended raw score per row."""
        sig = self._signals(df)
        ent = np.mean([self.scorers[k].score(v) for k, v in sig.items()], axis=0)
        freq = np.maximum(_num(df, "freq_DeviceInfo"), self.min_freq_)
        dev_rarity = np.where(_num(df, HAS_DEVICE) == 1, -np.log10(freq), 0.0)
        glob = np.mean(
            [
                self.scorers["global_amount"].score(_num(df, "amt_log")),
                dev_rarity,
                self.scorers["global_new_addr"].score(_num(df, "card_new_addr")),
            ],
            axis=0,
        )
        n = np.nan_to_num(_num(df, self.count_column), nan=0.0)
        w = n / (n + self.k)
        return pd.DataFrame(
            {"entity_part": ent, "global_part": glob, "w": w, "blend": w * ent + (1 - w) * glob},
            index=df.index,
        )

    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        """Blended entity/global score."""
        return self.parts(df)["blend"].to_numpy()

    def _explain_frame(self, frame: pd.DataFrame) -> dict[str, Any]:
        p = self.parts(frame).iloc[0]
        sig = {k: float(v[0]) for k, v in self._signals(frame).items()}
        return {
            "layer": self.name,
            "history_count": float(_num(frame, self.count_column)[0]),
            "weight_entity": round(float(p["w"]), 4),
            "entity_part": round(float(p["entity_part"]), 4),
            "global_part": round(float(p["global_part"]), 4),
            "signals": {k: (None if np.isnan(v) else round(v, 4)) for k, v in sig.items()},
        }
