"""Typed values: coercion for parameters, typing of source rows, normalization for comparing backends."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

NUMERIC = ("integer", "decimal")


def _iso(v: Any) -> str:
    if isinstance(v, dt.datetime):
        return v.replace(microsecond=0).isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v).replace(" ", "T", 1)


def parse_datetime(v: Any) -> dt.datetime | None:
    if v is None or isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    s = str(v).replace("Z", "+00:00")
    return dt.datetime.fromisoformat(s)


def accepts(type_: str, value: Any, values: list[str] | None = None) -> bool:
    if value is None:
        return True
    if type_ in ("string", "enum"):
        return isinstance(value, str) and (type_ != "enum" or not values or value in values)
    if type_ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_ == "decimal":
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if type_ == "boolean":
        return isinstance(value, bool)
    if type_ in ("date", "datetime"):
        try:
            parse_datetime(value)
            return True
        except (TypeError, ValueError):
            return False
    return False


def coerce(value: Any, type_: str) -> Any:
    """Turn a caller value into the form every adapter binds (ISO text for dates)."""
    if value is None:
        return None
    if type_ == "integer":
        return int(value)
    if type_ == "decimal":
        return float(value)
    if type_ == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "y")
        return bool(value)
    if type_ == "date":
        return _iso(value)[:10]
    if type_ == "datetime":
        return _iso(value)
    return str(value)


def from_source(value: Any, type_: str) -> Any:
    """Type a value read from a source row."""
    if value is None:
        return None
    if type_ == "boolean":
        return coerce(value, "boolean")
    if type_ == "integer":
        return int(value)
    if type_ == "decimal":
        return Decimal(str(value))
    if type_ in ("date", "datetime"):
        return coerce(value, type_)
    return str(value)


def normalize(value: Any, type_: str = "") -> Any:
    """Canonical form for comparing results across backends."""
    if value is None:
        return None
    if hasattr(value, "toPython"):
        value = value.toPython()
    if type_ == "boolean" or isinstance(value, bool):
        return coerce(value, "boolean")
    if type_ in NUMERIC or isinstance(value, (int, float, Decimal)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return str(value)
        return int(f) if f.is_integer() else round(f, 6)
    if type_ in ("date", "datetime") or isinstance(value, (dt.date, dt.datetime)):
        return _iso(value)[:10] if type_ == "date" else _iso(value)
    return str(value)
