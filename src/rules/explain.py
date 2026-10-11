"""Fill rule message templates with the record's real values (Turkish reasons)."""

from __future__ import annotations

import math
import string
from typing import Any

import numpy as np
import pandas as pd

MISSING_TEXT = "yok"


def to_python(value: Any) -> Any:
    """numpy/pandas scalar -> plain python value (None for missing)."""
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


class _Formatter(string.Formatter):
    """Missing values are printed as 'yok'; a format spec that does not fit falls back to str."""

    def format_field(self, value: Any, format_spec: str) -> str:
        value = to_python(value)
        if value is None:
            return MISSING_TEXT
        try:
            return super().format_field(value, format_spec)
        except (ValueError, TypeError):
            return str(value)


_FORMATTER = _Formatter()


def render_message(template: str, values: dict[str, Any]) -> str:
    """Fill a template; unknown placeholders are printed as 'yok'."""
    safe = {k: to_python(v) for k, v in values.items()}

    class _Default(dict):
        def __missing__(self, key: str) -> None:
            return None

    text = _FORMATTER.vformat(template, (), _Default(safe))
    return " ".join(text.split())
