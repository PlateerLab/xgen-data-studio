"""Read a SPARQL 1.1 SELECT (the subset the ontology can express) into the query IR."""
from __future__ import annotations

import re
from typing import Any

from xgen_data_studio.ir import (
    MAX_HOPS,
    Agg,
    And,
    Cmp,
    Column,
    Contains,
    Edge,
    Exists,
    In,
    IsNull,
    Not,
    Or,
    Order,
    Query,
    Ref,
)
from xgen_data_studio.model import Ontology
from xgen_data_studio.rdf import RDF_TYPE, Iris


class ParseError(ValueError):
    """The query uses something outside the subset the ontology IR can hold."""


_OPS = {"=": "eq", "!=": "ne", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte"}
_AGG = {"Aggregate_Count": "count", "Aggregate_Sum": "sum", "Aggregate_Avg": "avg", "Aggregate_Min": "min",
        "Aggregate_Max": "max", "Aggregate_Sample": "sample"}


def _alias(v) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(v))


class _Reader:
    def __init__(self, onto: Ontology):
        import rdflib

        self.rdflib = rdflib
        self.onto = onto
        self.iris = Iris(onto)
        self.nodes: dict[str, str] = {}
        self.props: dict[str, Ref] = {}
        self.edges: list[Edge] = []
        self.filters: list[Any] = []
        self.optional_nodes: set[str] = set()

    def local(self, term) -> str:
        name = self.iris.local(str(term))
        if name is None:
            raise ParseError(f"{term} is outside the ontology namespace {self.onto.namespace}")
        return name

    def term_name(self, t) -> str:
        if isinstance(t, self.rdflib.Variable):
            return _alias(t)
        raise ParseError(f"expected a variable, got {t}")

    def triple(self, s, p, o, *, optional: bool, scope: dict[str, str], edges: list, filters: list) -> None:
        R = self.rdflib
        if not isinstance(s, R.Variable):
            raise ParseError(f"subjects must be variables, got {s}")
        a = _alias(s)
        if not isinstance(p, R.URIRef):
            self.path(a, p, o, optional, edges)
            return
        if str(p) == RDF_TYPE:
            t = self.local(o)
            if t not in self.onto.objects:
                raise ParseError(f"unknown class {o}")
            scope.setdefault(a, t)
            return
        name = self.local(p)
        if name in self.onto.links or self.onto.link_by_inverse(name):
            if not isinstance(o, R.Variable):
                raise ParseError(f"link objects must be variables: {name}")
            edges.append(Edge(a, name, _alias(o), optional=optional))
            return
        if self.onto.property_type(name) is None:
            raise ParseError(f"'{name}' is neither a property nor a link of the ontology")
        if isinstance(o, R.Variable):
            self.props[_alias(o)] = Ref(a, name)
        else:
            filters.append(Cmp(Ref(a, name), "eq", o.toPython()))

    def path(self, a: str, p, o, optional: bool, edges: list) -> None:
        from rdflib.paths import AlternativePath, MulPath, SequencePath

        if isinstance(p, MulPath) and p.mod == "+":
            edges.append(Edge(a, self.local(p.path), _alias(o), optional=optional, min_hops=1, max_hops=MAX_HOPS))
            return
        if isinstance(p, AlternativePath):
            lengths, link = [], None
            for alt in p.args:
                steps = alt.args if isinstance(alt, SequencePath) else [alt]
                names = {self.local(x) for x in steps}
                if len(names) != 1:
                    raise ParseError("a path alternative must repeat one link")
                link = link or names.pop()
                lengths.append(len(steps))
            if sorted(lengths) == list(range(min(lengths), max(lengths) + 1)):
                edges.append(Edge(a, link, _alias(o), optional=optional, min_hops=min(lengths),
                                  max_hops=max(lengths)))
                return
        raise ParseError(f"unsupported property path {p}")

    def pattern(self, node, *, optional: bool, scope: dict[str, str], edges: list, filters: list) -> None:
        name = getattr(node, "name", "")
        if name == "BGP":
            for s, p, o in node["triples"]:
                self.triple(s, p, o, optional=optional, scope=scope, edges=edges, filters=filters)
        elif name == "Join":
            self.pattern(node["p1"], optional=optional, scope=scope, edges=edges, filters=filters)
            self.pattern(node["p2"], optional=optional, scope=scope, edges=edges, filters=filters)
        elif name == "LeftJoin":
            self.pattern(node["p1"], optional=optional, scope=scope, edges=edges, filters=filters)
            inner: dict[str, str] = {}
            self.pattern(node["p2"], optional=True, scope=inner, edges=edges, filters=filters)
            for a, t in inner.items():
                if a not in scope:
                    scope[a] = t
                    self.optional_nodes.add(a)
        elif name == "Filter":
            self.pattern(node["p"], optional=optional, scope=scope, edges=edges, filters=filters)
            filters.append(("expr", node["expr"], scope))
        elif name == "ToMultiSet":
            self.pattern(node["p"], optional=optional, scope=scope, edges=edges, filters=filters)
        elif name in ("Project", "Distinct", "Slice", "SelectQuery"):
            self.pattern(node["p"], optional=optional, scope=scope, edges=edges, filters=filters)
        else:
            raise ParseError(f"unsupported SPARQL pattern '{name}'")

    def ref(self, v) -> Ref:
        a = _alias(v)
        if a in self.props:
            return self.props[a]
        if a in self.nodes:
            return Ref(a, self.onto.objects[self.nodes[a]].key)
        raise ParseError(f"variable ?{a} is not bound to a property")

    def value(self, t) -> Any:
        if isinstance(t, self.rdflib.Variable):
            return self.ref(t)
        if isinstance(t, self.rdflib.Literal):
            v = t.toPython()
            return v.isoformat() if hasattr(v, "isoformat") else v
        raise ParseError(f"unsupported value {t}")

    def expr(self, e, scope: dict[str, str]) -> Any:
        name = getattr(e, "name", "")
        if name == "RelationalExpression":
            op, other = e["op"], e["other"]
            if op in ("IN", "NOT IN"):
                return In(self.ref(e["expr"]), [self.value(x) for x in other], negate=op == "NOT IN")
            if isinstance(e["expr"], self.rdflib.Variable):
                return Cmp(self.ref(e["expr"]), _OPS[op], self.value(other))
            flip = {"lt": "gt", "gt": "lt", "lte": "gte", "gte": "lte"}
            return Cmp(self.ref(other), flip.get(_OPS[op], _OPS[op]), self.value(e["expr"]))
        if name == "ConditionalAndExpression":
            return And([self.expr(x, scope) for x in [e["expr"], *e["other"]]])
        if name == "ConditionalOrExpression":
            return Or([self.expr(x, scope) for x in [e["expr"], *e["other"]]])
        if name == "UnaryNot":
            inner = self.expr(e["expr"], scope)
            if isinstance(inner, IsNull):
                return IsNull(inner.ref, negate=not inner.negate)
            return Not(inner)
        if name == "Builtin_BOUND":
            return IsNull(self.ref(e["arg"]), negate=True)
        if name == "Builtin_CONTAINS":
            arg = e["arg1"]
            if getattr(arg, "name", "") == "Builtin_STR":
                arg = arg["arg"]
            return Contains(self.ref(arg), self.value(e["arg2"]))
        if name in ("Builtin_EXISTS", "Builtin_NOTEXISTS"):
            inner: dict[str, str] = {}
            edges: list[Edge] = []
            filters: list[Any] = []
            self.pattern(e.graph, optional=False, scope=inner, edges=edges, filters=filters)
            new = {a: t for a, t in inner.items() if a not in self.nodes}
            where = self._filters(filters, {**self.nodes, **new})
            return Exists(new, edges, where, negate=name == "Builtin_NOTEXISTS")
        raise ParseError(f"unsupported SPARQL expression '{name or e}'")

    def _filters(self, items: list, scope: dict[str, str]) -> Any:
        out = []
        for f in items:
            out.append(self.expr(f[1], f[2]) if isinstance(f, tuple) else f)
        flat = []
        for f in out:
            flat += f.items if isinstance(f, And) else [f]
        return None if not flat else flat[0] if len(flat) == 1 else And(flat)


def parse_sparql(text: str, onto: Ontology) -> Query:
    try:
        from rdflib.plugins.sparql import prepareQuery
    except ImportError as e:
        raise ImportError("reading SPARQL needs the [rdf] extra (rdflib)") from e
    alg = prepareQuery(text).algebra
    rd = _Reader(onto)
    node, limit, distinct, order_exprs, extends, aggs = alg["p"], None, False, [], {}, {}
    project_vars = list(alg.get("PV") or [])
    while True:
        name = getattr(node, "name", "")
        if name == "Slice":
            limit = node["length"]
        elif name == "Distinct":
            distinct = True
        elif name == "Project":
            project_vars = list(node["PV"])
        elif name == "OrderBy":
            order_exprs = list(node["expr"])
        elif name == "Extend":
            extends[_alias(node["var"])] = node["expr"]
        elif name == "AggregateJoin":
            for a in node["A"]:
                aggs[_alias(a["res"])] = a
        elif name == "Group":
            pass
        else:
            break
        node = node["p"]
    edges: list[Edge] = []
    filters: list[Any] = []
    rd.pattern(node, optional=False, scope=rd.nodes, edges=edges, filters=filters)
    if not rd.nodes:
        raise ParseError("give each node variable a class with ?x a <Class>")
    for a in rd.optional_nodes:
        for e in edges:
            if a in (e.source, e.target):
                e.optional = True
    where = rd._filters(filters, rd.nodes)

    def column_expr(v) -> Ref | Agg:
        a = _alias(v)
        if a in extends:
            inner = extends[a]
            if hasattr(inner, "name"):
                raise ParseError(f"unsupported select expression for ?{a}")
            return column_expr(inner)
        if a in aggs:
            ag = aggs[a]
            func = _AGG.get(ag.name)
            if func is None:
                raise ParseError(f"unsupported aggregate {ag.name}")
            arg = ag.get("vars")
            if func == "sample":
                return rd.ref(arg)
            if func == "count" and (arg is None or str(arg) == "*"):
                return Agg("count_distinct" if ag.get("distinct") == "DISTINCT" else "count")
            distinct_agg = ag.get("distinct") == "DISTINCT"
            if func == "count" and _alias(arg) in rd.nodes:
                return Agg("count_distinct" if distinct_agg else "count", node=_alias(arg))
            return Agg("count_distinct" if func == "count" and distinct_agg else func, rd.ref(arg))
        return rd.ref(v)

    columns = [Column(column_expr(v), _alias(v)) for v in project_vars]
    by_var = {}
    for c in columns:
        by_var[c.name] = c.name
        if isinstance(c.expr, Ref):
            for pv, r in rd.props.items():
                if r == c.expr:
                    by_var.setdefault(pv, c.name)
    for res, ag in aggs.items():
        for v, e in extends.items():
            if _alias(e) == res and v in by_var:
                by_var[res] = by_var[v]
    order = []
    for oc in order_exprs:
        desc = getattr(oc, "name", "") == "OrderCondition" and oc.get("order") == "DESC"
        e = oc["expr"] if getattr(oc, "name", "") == "OrderCondition" else oc
        key = _alias(e) if not hasattr(e, "name") else None
        if key is None:
            continue
        if key not in by_var and key in aggs:
            want = column_expr(e)
            by_var.update({key: c.name for c in columns if c.expr == want})
        if key not in by_var:
            raise ParseError(f"order by ?{key}: order by a selected column")
        order.append(Order(by_var[key], desc))
    return Query(nodes=dict(rd.nodes), edges=edges, where=where, columns=columns, order=order, limit=limit,
                 distinct=distinct)
