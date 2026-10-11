"""Values the context rules learn from the FIT set (thresholds, dominant addr2)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.context.config import ContextConfig

PARAMS_FILE = "context_params.json"


@dataclass
class ContextParams:
    """Learned parameters referenced in conditions as {param: name}."""

    values: dict[str, Any] = field(default_factory=dict)
    n_fit: int = 0

    @classmethod
    def fit(cls, fit_df: pd.DataFrame, cfg: ContextConfig) -> ContextParams:
        """Learn every `learned_params` entry from fit rows only.

        An entry with `quantile` gives that quantile of the column; an entry without it gives the
        most frequent non-null value of the column.
        """
        values: dict[str, Any] = {}
        for name, spec in cfg.learned_params.items():
            col = fit_df[spec["column"]]
            if "quantile" in spec:
                values[name] = float(np.quantile(col.dropna().astype("float64"), spec["quantile"]))
            else:
                mode = col.dropna().value_counts().idxmax()
                values[name] = mode.item() if isinstance(mode, np.generic) else mode
        return cls(values=values, n_fit=len(fit_df))

    def get(self, name: str) -> Any:
        """Return a learned value (KeyError names the missing parameter)."""
        if name not in self.values:
            raise KeyError(f"learned context param {name!r} is missing; run scripts/run_context.py")
        return self.values[name]

    def save(self, directory: Path) -> Path:
        """Write the parameters as readable JSON."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / PARAMS_FILE
        path.write_text(json.dumps({"values": self.values, "n_fit": self.n_fit}, indent=2))
        return path

    @classmethod
    def load(cls, directory: Path) -> ContextParams:
        """Read parameters written by save()."""
        data = json.loads((directory / PARAMS_FILE).read_text())
        return cls(values=data["values"], n_fit=int(data["n_fit"]))
