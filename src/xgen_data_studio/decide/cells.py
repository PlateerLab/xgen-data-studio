"""Unary tests for decision-table cells: a small FEEL/ZEN subset, evaluated natively or rendered for ZEN."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


class CellError(ValueError):
    """A decision cell is not a valid unary test."""


@dataclass(frozen=True)
class Any_:
    pass


@dataclass(frozen=True)
class IsNull:
    negate: bool = False


@dataclass(frozen=True)
class Compare:
    op: str
    value: Any


@dataclass(frozen=True)
class Range:
    low: Any
    high: Any
    low_inclusive: bool = True
    high_inclusive: bool = True


@dataclass(frozen=True)
class OneOf:
    values: tuple
    negate: bool = False


_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_RANGE = re.compile(r"^([\[(])\s*(.+?)\s*\.\.\s*(.+?)\s*([\])])$")
_CMP = re.compile(r"^(<=|>=|<|>|!=|==|=)\s*(.+)$")


def _literal(s: str) -> Any:
    s = s.strip()
    if s == "null":
        return None
    if s in ("true", "false"):
        return s == "true"
    if _NUM.match(s):
        return float(s) if "." in s else int(s)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    raise CellError(f"'{s}' is not a literal; quote text as \"text\"")


def _split_list(s: str) -> list[str]:
    out, buf, quote = [], "", ""
    for ch in s:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [x.strip() for x in out if x.strip()]


def parse_test(text: Any) -> Any:
    s = "" if text is None else str(text).strip()
    if s in ("", "-"):
        return Any_()
    if s == "null":
        return IsNull()
    if s == "not null":
        return IsNull(negate=True)
    m = _RANGE.match(s)
    if m:
        return Range(_literal(m.group(2)), _literal(m.group(3)), m.group(1) == "[", m.group(4) == "]")
    low = s.lower()
    for prefix, neg in (("not in", True), ("in", False)):
        if low.startswith(prefix + " ") or low.startswith(prefix + "["):
            body = s[len(prefix):].strip()
            if not (body.startswith("[") and body.endswith("]")):
                raise CellError(f"'{s}': list goes in [ ]")
            return OneOf(tuple(_literal(x) for x in _split_list(body[1:-1])), negate=neg)
    m = _CMP.match(s)
    if m:
        op = {"=": "==", "==": "=="}.get(m.group(1), m.group(1))
        return Compare(op, _literal(m.group(2)))
    parts = _split_list(s)
    if len(parts) > 1:
        return OneOf(tuple(_literal(x) for x in parts))
    return Compare("==", _literal(s))


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def evaluate(test: Any, value: Any) -> bool:
    if isinstance(test, Any_):
        return True
    if isinstance(test, IsNull):
        return (value is None) != test.negate
    if value is None:
        return isinstance(test, Compare) and test.op == "!=" and test.value is not None
    if isinstance(test, Compare):
        a, b = _num(value), _num(test.value)
        if test.op == "==":
            return a == b
        if test.op == "!=":
            return a != b
        try:
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[test.op]
        except TypeError:
            return False
    if isinstance(test, Range):
        a = _num(value)
        try:
            lo = a >= _num(test.low) if test.low_inclusive else a > _num(test.low)
            hi = a <= _num(test.high) if test.high_inclusive else a < _num(test.high)
        except TypeError:
            return False
        return lo and hi
    if isinstance(test, OneOf):
        return (_num(value) in [_num(x) for x in test.values]) != test.negate
    raise CellError(f"unknown test {test!r}")


def to_zen(test: Any) -> str:
    """Render as a ZEN unary expression over `$`."""
    lit = json.dumps
    if isinstance(test, Any_):
        return ""
    if isinstance(test, IsNull):
        return "$ != null" if test.negate else "$ == null"
    if isinstance(test, Compare):
        return f"$ {test.op} {lit(test.value)}"
    if isinstance(test, Range):
        lo = ">=" if test.low_inclusive else ">"
        hi = "<=" if test.high_inclusive else "<"
        return f"$ {lo} {lit(test.low)} and $ {hi} {lit(test.high)}"
    if isinstance(test, OneOf):
        body = f"$ in [{', '.join(lit(v) for v in test.values)}]"
        return f"not ({body})" if test.negate else body
    raise CellError(f"unknown test {test!r}")
