"""Check an IR query against the ontology: resolve link directions, type literals and parameters."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from xgen_data_studio.ir import (
    MAX_HOPS,
    OPS,
    Agg,
    And,
    Cmp,
    Contains,
    Edge,
    Exists,
    In,
    IsNull,
    Not,
    Or,
    Param,
    Query,
    Ref,
)
from xgen_data_studio.model import Ontology
from xgen_data_studio.values import accepts


class CheckError(ValueError):
    """The query does not fit the ontology."""

    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


@dataclass
class Checked:
    query: Query
    issues: list[str] = field(default_factory=list)
    param_types: dict[str, str] = field(default_factory=dict)
    column_types: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def raise_for_issues(self) -> Checked:
        if self.issues:
            raise CheckError(self.issues)
        return self


def is_a(onto: Ontology, type_name: str, base: str) -> bool:
    seen = set()
    t = type_name
    while t and t not in seen:
        if t == base:
            return True
        seen.add(t)
        t = onto.objects[t].parent if t in onto.objects else ""
    return False


class _Checker:
    def __init__(self, onto: Ontology):
        self.onto = onto
        self.issues: list[str] = []
        self.params: dict[str, str] = {}

    def issue(self, msg: str) -> None:
        if msg not in self.issues:
            self.issues.append(msg)

    def prop_type(self, scope: dict[str, str], ref: Ref) -> str | None:
        t = scope.get(ref.alias)
        if t is None:
            self.issue(f"unknown alias '{ref.alias}' in {ref}")
            return None
        obj = self.onto.objects.get(t)
        if obj is None:
            return None
        p = _find_prop(self.onto, t, ref.prop)
        if p is None:
            known = ", ".join(sorted(_all_props(self.onto, t)))
            self.issue(f"{t} ('{ref.alias}') has no property '{ref.prop}'; it has: {known}")
            return None
        return p.type

    def edge(self, e: Edge, scope: dict[str, str]) -> Edge:
        lk = self.onto.links.get(e.link)
        via_inverse = False
        if lk is None:
            lk = self.onto.link_by_inverse(e.link)
            via_inverse = lk is not None
        if lk is None:
            self.issue(f"unknown link '{e.link}'; links are: {', '.join(sorted(self.onto.links))}")
            return e
        st, tt = scope.get(e.source), scope.get(e.target)
        if st is None or tt is None:
            self.issue(f"edge {e.source}-{e.link}-{e.target} uses an alias that is not matched")
            return e
        fwd = is_a(self.onto, st, lk.source) and is_a(self.onto, tt, lk.target)
        back = is_a(self.onto, st, lk.target) and is_a(self.onto, tt, lk.source)
        if e.reverse is not None:
            rev = e.reverse
        elif via_inverse:
            rev = back or not fwd
        else:
            rev = not fwd and back
        if (rev and not back) or (not rev and not fwd):
            self.issue(f"link '{e.link}' goes {lk.source} -> {lk.target}; it cannot join {e.source}:{st} and "
                       f"{e.target}:{tt}")
        if e.hops:
            if lk.source != lk.target:
                self.issue(f"hops on '{lk.name}' need a link from a type to itself")
            if not (1 <= e.min_hops <= e.max_hops <= MAX_HOPS):
                self.issue(f"hops must satisfy 1 <= min <= max <= {MAX_HOPS}")
        return replace(e, link=lk.name, reverse=rev)

    def edges(self, edges: list[Edge], scope: dict[str, str], bound: set[str], new: set[str],
              where: str) -> list[Edge]:
        out = []
        optional: set[str] = set()
        for e in edges:
            if e.source not in bound and e.target not in bound:
                self.issue(f"{where}: edge {e.source}-{e.link}-{e.target} touches no earlier alias; list edges so "
                           "each one starts from an alias already joined")
            if not e.optional and (e.source in optional or e.target in optional):
                self.issue(f"{where}: edge {e.source}-{e.link}-{e.target} hangs off an optional alias; mark it "
                           "optional too")
            if e.optional:
                optional |= {e.source, e.target} - bound
            out.append(self.edge(e, scope))
            bound |= {e.source, e.target}
        for a in new - bound:
            self.issue(f"{where}: alias '{a}' is not connected by any edge")
        return out

    def value(self, ref_type: str | None, value: Any, scope: dict[str, str], ctx: str, values=None) -> None:
        if ref_type is None:
            return
        if isinstance(value, Param):
            prev = self.params.get(value.name)
            if prev and prev != ref_type and {prev, ref_type} != {"string", "enum"}:
                self.issue(f"parameter '{value.name}' is used as {prev} and {ref_type}")
            self.params.setdefault(value.name, ref_type)
        elif isinstance(value, Ref):
            other = self.prop_type(scope, value)
            if other and not _comparable(ref_type, other):
                self.issue(f"{ctx}: cannot compare {ref_type} with {other}")
        elif not accepts(ref_type, value, values):
            hint = f" (one of {values})" if values else ""
            self.issue(f"{ctx}: {value!r} is not a valid {ref_type}{hint}")

    def filt(self, f: Any, scope: dict[str, str]) -> Any:
        if f is None:
            return None
        if isinstance(f, Cmp):
            if f.op not in OPS:
                self.issue(f"unknown comparison '{f.op}'")
            t = self.prop_type(scope, f.ref)
            self.value(t, f.value, scope, str(f.ref), self._enum_values(scope, f.ref))
            if t in ("boolean",) and f.op not in ("eq", "ne"):
                self.issue(f"{f.ref}: booleans only support eq/ne")
            return f
        if isinstance(f, In):
            t = self.prop_type(scope, f.ref)
            for v in f.values:
                self.value(t, v, scope, str(f.ref), self._enum_values(scope, f.ref))
            return f
        if isinstance(f, Contains):
            t = self.prop_type(scope, f.ref)
            if t and t not in ("string", "enum"):
                self.issue(f"contains needs a text property, {f.ref} is {t}")
            self.value("string", f.value, scope, str(f.ref))
            return f
        if isinstance(f, IsNull):
            self.prop_type(scope, f.ref)
            return f
        if isinstance(f, And):
            return And([self.filt(x, scope) for x in f.items])
        if isinstance(f, Or):
            return Or([self.filt(x, scope) for x in f.items])
        if isinstance(f, Not):
            return Not(self.filt(f.item, scope))
        if isinstance(f, Exists):
            clash = set(f.nodes) & set(scope)
            if clash:
                self.issue(f"exists reuses aliases {sorted(clash)}")
            for a, t in f.nodes.items():
                self._type(t, a)
            inner = {**scope, **f.nodes}
            if not f.edges:
                self.issue("exists needs at least one edge from an outer alias")
            edges = self.edges(f.edges, inner, set(scope), set(f.nodes), "exists")
            return replace(f, edges=edges, where=self.filt(f.where, inner))
        self.issue(f"unknown filter {f!r}")
        return f

    def _enum_values(self, scope, ref: Ref):
        t = scope.get(ref.alias)
        p = _find_prop(self.onto, t, ref.prop) if t in self.onto.objects else None
        return p.values if p is not None and p.type == "enum" else None

    def _type(self, t: str, alias: str) -> None:
        if t not in self.onto.objects:
            self.issue(f"alias '{alias}': unknown object type '{t}'; types are: {', '.join(sorted(self.onto.objects))}")

    def query(self, q: Query) -> Checked:
        for a, t in q.nodes.items():
            self._type(t, a)
        scope = dict(q.nodes)
        root = next(iter(q.nodes))
        edges = self.edges(q.edges, scope, {root}, set(q.nodes) - {root}, "match")
        where = self.filt(q.where, scope)
        col_types: dict[str, str] = {}
        for c in q.columns:
            col_types[c.name] = self._column_type(c.expr, scope) or "string"
        names = {c.name for c in q.columns}
        for o in q.order:
            if o.name not in names:
                self.issue(f"order by '{o.name}' is not a returned column; columns are: {sorted(names)}")
        if q.limit is not None and q.limit <= 0:
            self.issue("limit must be positive")
        resolved = replace(q, edges=edges, where=where)
        return Checked(resolved, self.issues, self.params, col_types)

    def _column_type(self, e: Ref | Agg, scope: dict[str, str]) -> str | None:
        if isinstance(e, Ref):
            return self.prop_type(scope, e)
        if e.func in ("count", "count_distinct"):
            if e.node and e.node not in scope:
                self.issue(f"{e.func}: unknown alias '{e.node}'")
            if e.ref is not None:
                self.prop_type(scope, e.ref)
            if e.func == "count_distinct" and e.ref is None and not e.node:
                self.issue("count_distinct needs a property or alias")
            return "integer"
        if e.ref is None:
            self.issue(f"{e.func} needs a property")
            return None
        t = self.prop_type(scope, e.ref)
        if e.func in ("sum", "avg") and t and t not in ("integer", "decimal"):
            self.issue(f"{e.func} needs a number, {e.ref} is {t}")
        if e.func == "avg":
            return "decimal"
        return t


def _find_prop(onto: Ontology, type_name: str | None, name: str):
    t = type_name
    seen = set()
    while t and t in onto.objects and t not in seen:
        seen.add(t)
        obj = onto.objects[t]
        if name in obj.properties:
            return obj.properties[name]
        t = obj.parent
    return None


def _all_props(onto: Ontology, type_name: str) -> set[str]:
    out: set[str] = set()
    t = type_name
    seen = set()
    while t and t in onto.objects and t not in seen:
        seen.add(t)
        out |= set(onto.objects[t].properties)
        t = onto.objects[t].parent
    return out


def find_prop(onto: Ontology, type_name: str, name: str):
    p = _find_prop(onto, type_name, name)
    if p is None:
        raise CheckError([f"{type_name} has no property '{name}'"])
    return p


def _comparable(a: str, b: str) -> bool:
    groups = [{"string", "enum"}, {"integer", "decimal"}, {"date", "datetime"}, {"boolean"}]
    return any(a in g and b in g for g in groups)


def check(q: Query, onto: Ontology) -> Checked:
    return _Checker(onto).query(q)


def check_or_raise(q: Query | dict, onto: Ontology) -> Checked:
    if isinstance(q, dict):
        q = Query.from_dict(q)
    return check(q, onto).raise_for_issues()


def aliases_of(q: Query) -> dict[str, str]:
    """All aliases in the query, including those bound inside exists bodies."""
    out = dict(q.nodes)

    def walk(f):
        if isinstance(f, (And, Or)):
            for x in f.items:
                walk(x)
        elif isinstance(f, Not):
            walk(f.item)
        elif isinstance(f, Exists):
            out.update(f.nodes)
            walk(f.where)

    walk(q.where)
    return out


def column_refs(q: Query) -> list[Ref]:
    out = []
    for c in q.columns:
        if isinstance(c.expr, Ref):
            out.append(c.expr)
        elif isinstance(c.expr, Agg) and c.expr.ref is not None:
            out.append(c.expr.ref)
    return out
