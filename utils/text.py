from __future__ import annotations

from typing import Any


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def join_nonempty(*parts: Any, sep: str = " · ") -> str:
    return sep.join(text for text in map(clean, parts) if text)


def yuan(cents: Any) -> str:
    if cents is None or isinstance(cents, bool):
        return ""
    try:
        amount = float(cents) / 100
    except (TypeError, ValueError):
        return ""
    return f"{amount:g}元"


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def to_int(value: Any, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number


def to_float(value: Any, default: float, *, lo: float | None = None, hi: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number
