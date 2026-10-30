"""Ontology query IR: a typed graph pattern over object types, compiled per backend."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Union

OPS = {"eq": "=", "ne": "!=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
AGGS = ("count", "count_distinct", "sum", "avg", "min", "max")
MAX_HOPS = 10


class IRError(ValueError):
    """The IR document is malformed."""


@dataclass(frozen=True)
class Param:
    name: str


@dataclass(frozen=True)
class Ref:
    alias: str
    prop: str

    def __str__(self) -> str:
        return f"{self.alias}.{self.prop}"


@dataclass
class Edge:
    source: str
    link: str
    target: str
    optional: bool = False
    min_hops: int = 1
    max_hops: int = 1
    reverse: bool | None = None

    @property
    def hops(self) -> bool:
        return (self.min_hops, self.max_hops) != (1, 1)


@dataclass
class Cmp:
    ref: Ref
    op: str
    value: Any


@dataclass
class In:
    ref: Ref
    values: list
    negate: bool = False


@dataclass
class Contains:
    ref: Ref
    value: Any


@dataclass
class IsNull:
    ref: Ref
    negate: bool = False


@dataclass
class And:
    items: list


@dataclass
class Or:
    items: list


@dataclass
class Not:
    item: Any


@dataclass
class Exists:
    nodes: dict[str, str]
    edges: list[Edge]
    where: Any = None
    negate: bool = False


Filter = Union[Cmp, In, Contains, IsNull, And, Or, Not, Exists]


@dataclass
class Agg:
    func: str
    ref: Ref | None = None
    node: str = ""


@dataclass
class Column:
    expr: Ref | Agg
    name: str


@dataclass
class Order:
    name: str
    desc: bool = False


@dataclass
class Query:
    nodes: dict[str, str]
    edges: list[Edge] = field(default_factory=list)
    where: Any = None
    columns: list[Column] = field(default_factory=list)
    order: list[Order] = field(default_factory=list)
    limit: int | None = None
    distinct: bool = False

    @property
    def aggregated(self) -> bool:
        return any(isinstance(c.expr, Agg) for c in self.columns)

    def with_where(self, extra: Any) -> Query:
        if extra is None:
            return self
        where = extra if self.where is None else And([self.where, extra])
        return replace(self, where=where)

    @classmethod
    def from_dict(cls, d: dict) -> Query:
        return _query(d)

    def to_dict(self) -> dict:
        return _dump_query(self)


def parse_ref(s: Any) -> Ref:
    if isinstance(s, Ref):
        return s
    if not isinstance(s, str) or s.count(".") != 1:
        raise IRError(f"expected 'alias.property', got {s!r}")
    a, p = s.split(".")
    if not a or not p:
        raise IRError(f"expected 'alias.property', got {s!r}")
    return Ref(a, p)


def _value(v: Any) -> Any:
    if isinstance(v, dict):
        if set(v) == {"param"}:
            return Param(v["param"])
        if set(v) == {"ref"}:
            return parse_ref(v["ref"])
        raise IRError(f"unknown value form {v!r}")
    return v


def _edge(e: Any) -> Edge:
    if isinstance(e, (list, tuple)):
        if len(e) != 3:
            raise IRError(f"edge must be [source, link, target], got {e!r}")
        return Edge(e[0], e[1], e[2])
    hops = e.get("hops", [1, 1])
    if isinstance(hops, int):
        hops = [1, hops]
    if len(hops) != 2:
        raise IRError("hops takes [min, max]")
    return Edge(e["from"], e["link"], e["to"], optional=bool(e.get("optional", False)),
                min_hops=int(hops[0]), max_hops=int(hops[1]), reverse=e.get("reverse"))


def parse_filter(d: Any) -> Any:
    if d is None:
        return None
    if not isinstance(d, dict) or len(d) != 1:
        raise IRError(f"a filter is a one-key object, got {d!r}")
    (k, v), = d.items()
    if k in OPS:
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise IRError(f"{k} takes [ref, value]")
        return Cmp(parse_ref(v[0]), k, _value(v[1]))
    if k in ("in", "not_in"):
        values = _value(v[1])
        if not isinstance(values, list):
            raise IRError(f"{k} takes a literal list")
        return In(parse_ref(v[0]), values, negate=k == "not_in")
    if k == "contains":
        return Contains(parse_ref(v[0]), _value(v[1]))
    if k in ("is_null", "not_null"):
        return IsNull(parse_ref(v), negate=k == "not_null")
    if k in ("and", "or"):
        items = [parse_filter(x) for x in v]
        if not items:
            raise IRError(f"{k} needs at least one item")
        return And(items) if k == "and" else Or(items)
    if k == "not":
        return Not(parse_filter(v))
    if k in ("exists", "not_exists"):
        return Exists(nodes=dict(v.get("match", {})), edges=[_edge(e) for e in v.get("edges", [])],
                      where=parse_filter(v.get("where")), negate=k == "not_exists")
    raise IRError(f"unknown filter '{k}'")


def _column(c: Any, nodes: dict[str, str]) -> tuple[Ref | Agg, str | None]:
    if isinstance(c, str):
        return parse_ref(c), None
    if "col" in c:
        return parse_ref(c["col"]), c.get("as")
    for f in AGGS:
        if f in c:
            arg = c[f]
            if arg == "*":
                return Agg(f), c.get("as")
            if isinstance(arg, str) and "." not in arg:
                if arg not in nodes:
                    raise IRError(f"{f}: unknown alias '{arg}'")
                return Agg(f, node=arg), c.get("as")
            return Agg(f, parse_ref(arg)), c.get("as")
    raise IRError(f"unknown column form {c!r}")


def _default_names(cols: list[tuple[Ref | Agg, str | None]]) -> list[Column]:
    props = [e.prop for e, n in cols if isinstance(e, Ref) and n is None]
    out = []
    for expr, name in cols:
        if name is None:
            if isinstance(expr, Ref):
                name = expr.prop if props.count(expr.prop) == 1 else f"{expr.alias}_{expr.prop}"
            elif expr.ref is not None:
                name = f"{expr.func}_{expr.ref.alias}_{expr.ref.prop}"
            else:
                name = f"{expr.func}_{expr.node}" if expr.node else expr.func
        out.append(Column(expr, name))
    names = [c.name for c in out]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise IRError(f"duplicate column names {sorted(dup)}")
    return out


def _query(d: dict) -> Query:
    if not isinstance(d, dict):
        raise IRError("a query is an object")
    nodes = d.get("match")
    if not isinstance(nodes, dict) or not nodes:
        raise IRError("'match' maps aliases to object types")
    cols = [_column(c, nodes) for c in d.get("return", [])]
    if not cols:
        raise IRError("'return' lists at least one column")
    order = []
    for o in d.get("order", []):
        o = str(o)
        order.append(Order(o[1:], True) if o.startswith("-") else Order(o))
    limit = d.get("limit")
    return Query(nodes=dict(nodes), edges=[_edge(e) for e in d.get("edges", [])], where=parse_filter(d.get("where")),
                 columns=_default_names(cols), order=order, limit=int(limit) if limit is not None else None,
                 distinct=bool(d.get("distinct", False)))


def _dump_value(v: Any) -> Any:
    if isinstance(v, Param):
        return {"param": v.name}
    if isinstance(v, Ref):
        return {"ref": str(v)}
    return v


def _dump_edge(e: Edge) -> Any:
    if not e.optional and not e.hops and e.reverse is None:
        return [e.source, e.link, e.target]
    out: dict[str, Any] = {"from": e.source, "link": e.link, "to": e.target}
    if e.optional:
        out["optional"] = True
    if e.hops:
        out["hops"] = [e.min_hops, e.max_hops]
    if e.reverse is not None:
        out["reverse"] = e.reverse
    return out


def dump_filter(f: Any) -> Any:
    if f is None:
        return None
    if isinstance(f, Cmp):
        return {f.op: [str(f.ref), _dump_value(f.value)]}
    if isinstance(f, In):
        return {"not_in" if f.negate else "in": [str(f.ref), list(f.values)]}
    if isinstance(f, Contains):
        return {"contains": [str(f.ref), _dump_value(f.value)]}
    if isinstance(f, IsNull):
        return {"not_null" if f.negate else "is_null": str(f.ref)}
    if isinstance(f, And):
        return {"and": [dump_filter(x) for x in f.items]}
    if isinstance(f, Or):
        return {"or": [dump_filter(x) for x in f.items]}
    if isinstance(f, Not):
        return {"not": dump_filter(f.item)}
    if isinstance(f, Exists):
        body: dict[str, Any] = {"match": dict(f.nodes), "edges": [_dump_edge(e) for e in f.edges]}
        if f.where is not None:
            body["where"] = dump_filter(f.where)
        return {"not_exists" if f.negate else "exists": body}
    raise IRError(f"cannot dump {f!r}")


def _dump_column(c: Column) -> Any:
    e = c.expr
    if isinstance(e, Ref):
        return {"col": str(e), "as": c.name}
    arg = str(e.ref) if e.ref is not None else (e.node or "*")
    return {e.func: arg, "as": c.name}


def _dump_query(q: Query) -> dict:
    out: dict[str, Any] = {"match": dict(q.nodes)}
    if q.edges:
        out["edges"] = [_dump_edge(e) for e in q.edges]
    if q.where is not None:
        out["where"] = dump_filter(q.where)
    out["return"] = [_dump_column(c) for c in q.columns]
    if q.order:
        out["order"] = [("-" if o.desc else "") + o.name for o in q.order]
    if q.limit is not None:
        out["limit"] = q.limit
    if q.distinct:
        out["distinct"] = True
    return out


def walk_filters(f: Any):
    """Yield every filter node, descending into And/Or/Not but not into Exists bodies."""
    if f is None:
        return
    yield f
    if isinstance(f, (And, Or)):
        for x in f.items:
            yield from walk_filters(x)
    elif isinstance(f, Not):
        yield from walk_filters(f.item)


def filter_refs(f: Any, deep: bool = True):
    for x in walk_filters(f):
        if isinstance(x, (Cmp, In, Contains, IsNull)):
            yield x.ref
            if isinstance(x, Cmp) and isinstance(x.value, Ref):
                yield x.value
        elif isinstance(x, Exists) and deep:
            yield from filter_refs(x.where, deep)


def params_of(f: Any):
    for x in walk_filters(f):
        if isinstance(x, (Cmp, Contains)) and isinstance(x.value, Param):
            yield x, x.value
        elif isinstance(x, Exists):
            yield from params_of(x.where)
