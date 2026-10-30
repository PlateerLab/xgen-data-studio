"""IR -> SPARQL 1.1 over the projected graph (same IRIs as the projection and R2RML export)."""
from __future__ import annotations

from xgen_data_studio.check import aliases_of, find_prop
from xgen_data_studio.compile.base import Compiled, CompileError, Compiler, Params, marker
from xgen_data_studio.ir import Agg, And, Cmp, Contains, Edge, Exists, In, IsNull, Not, Or, Query, Ref, filter_refs
from xgen_data_studio.rdf import RDF_TYPE, Iris, iri, literal

_OP = {"eq": "=", "ne": "!=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def var(ref: Ref) -> str:
    return f"?{ref.alias}__{ref.prop}"


class SparqlCompiler(Compiler):
    language = "sparql"
    dialect = "1.1"

    def compile(self, q: Query | dict) -> Compiled:
        chk = self.checked(q)
        q = chk.query
        self._types = aliases_of(q)
        self._iris = Iris(self.onto)
        self._params = Params(chk.param_types)
        where = self._filter(q.where) if q.where is not None else None
        body = self._group(q, where)
        cols, group = [], []
        for c in q.columns:
            if isinstance(c.expr, Ref):
                v = var(c.expr)
                group.append(v)
                cols.append(f"({v} AS ?{c.name})")
            else:
                cols.append(f"({self._agg(c.expr)} AS ?{c.name})")
        lines = ["SELECT " + ("DISTINCT " if q.distinct else "") + " ".join(cols), "WHERE {", *body, "}"]
        if q.aggregated and group:
            lines.append("GROUP BY " + " ".join(group))
        if q.order:
            by = {c.name: c.expr for c in q.columns}
            keys = []
            for o in q.order:
                e = by[o.name]
                if isinstance(e, Ref):
                    keys.append(f"(IF(BOUND({var(e)}), 0, 1))")
                    expr = var(e)
                else:
                    expr = self._agg(e)
                keys.append(f"DESC({expr})" if o.desc else f"ASC({expr})")
            lines.append("ORDER BY " + " ".join(keys))
        if q.limit is not None:
            lines.append(f"LIMIT {int(q.limit)}")
        names = list(dict.fromkeys(self._params.order))
        return Compiled("sparql", self.dialect, "\n".join(lines), "inline", names, self._params.types,
                        [c.name for c in q.columns], chk.column_types, self._params.literals, render=literal)

    def _type(self, alias: str) -> str:
        return f"?{alias} {iri(RDF_TYPE)} {iri(self._iris.cls(self._types[alias]))} ."

    def _edge(self, e: Edge) -> str:
        p = iri(self._iris.link(e.link))
        s, t = (e.target, e.source) if e.reverse else (e.source, e.target)
        if not e.hops:
            return f"?{s} {p} ?{t} ."
        path = "|".join("/".join([p] * k) for k in range(e.min_hops, e.max_hops + 1))
        return f"{{ SELECT DISTINCT ?{s} ?{t} WHERE {{ ?{s} ({path}) ?{t} . }} }}"

    def _props(self, alias: str, props: set[str]) -> list[str]:
        out = []
        for p in sorted(props):
            find_prop(self.onto, self._types[alias], p)
            out.append(f"OPTIONAL {{ ?{alias} {iri(self._iris.prop(p))} {var(Ref(alias, p))} . }}")
        return out

    def _needed(self, q: Query) -> dict[str, set[str]]:
        need: dict[str, set[str]] = {}
        refs = list(filter_refs(q.where, deep=False))
        for c in q.columns:
            if isinstance(c.expr, Ref):
                refs.append(c.expr)
            elif isinstance(c.expr, Agg) and c.expr.ref is not None:
                refs.append(c.expr.ref)
        for r in refs:
            need.setdefault(r.alias, set()).add(r.prop)
        return need

    def _group(self, q: Query, where: str | None) -> list[str]:
        root = next(iter(q.nodes))
        need = self._needed(q)
        lines = ["  " + self._type(root)]
        optional, bound = set(), {root}
        for e in q.edges:
            new = None if {e.source, e.target} <= bound else (e.target if e.source in bound else e.source)
            types = [self._type(new)] if new else []
            if e.optional:
                optional.add(new)
                inner = [self._edge(e), *types, *self._props(new, need.get(new, set()))]
                lines.append("  OPTIONAL { " + " ".join(inner) + " }")
            else:
                lines += ["  " + self._edge(e)] + ["  " + t for t in types]
            bound |= {e.source, e.target}
        for a in q.nodes:
            if a not in optional:
                lines += ["  " + x for x in self._props(a, need.get(a, set()))]
        if where:
            lines.append(f"  FILTER({where})")
        return lines

    def _ph(self, value, ref: Ref) -> str:
        p = find_prop(self.onto, self._types[ref.alias], ref.prop)
        return marker(self._params.add(value, p.type))

    def _filter(self, f) -> str:
        if isinstance(f, Cmp):
            rhs = var(f.value) if isinstance(f.value, Ref) else self._ph(f.value, f.ref)
            return f"{var(f.ref)} {_OP[f.op]} {rhs}"
        if isinstance(f, In):
            if not f.values:
                return "true" if f.negate else "false"
            items = ", ".join(self._ph(v, f.ref) for v in f.values)
            return f"{var(f.ref)} {'NOT IN' if f.negate else 'IN'} ({items})"
        if isinstance(f, Contains):
            return f"CONTAINS(STR({var(f.ref)}), {self._ph(f.value, f.ref)})"
        if isinstance(f, IsNull):
            return f"{'' if f.negate else '!'}BOUND({var(f.ref)})"
        if isinstance(f, And):
            return "(" + " && ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Or):
            return "(" + " || ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Not):
            return f"!({self._filter(f.item)})"
        if isinstance(f, Exists):
            return self._exists(f)
        raise CompileError(f"cannot compile filter {f!r}")

    def _exists(self, f: Exists) -> str:
        parts = []
        known = set(self._types) - set(f.nodes)
        for e in f.edges:
            parts.append(self._edge(e))
            for a in (e.source, e.target):
                if a not in known:
                    parts.append(self._type(a))
                    known.add(a)
        need: dict[str, set[str]] = {}
        for r in filter_refs(f.where, deep=False):
            need.setdefault(r.alias, set()).add(r.prop)
        for a, props in need.items():
            parts += self._props(a, props)
        if f.where is not None:
            parts.append(f"FILTER({self._filter(f.where)})")
        return f"{'NOT ' if f.negate else ''}EXISTS {{ {' '.join(parts)} }}"

    def _agg(self, a: Agg) -> str:
        if a.func in ("count", "count_distinct"):
            arg = var(a.ref) if a.ref is not None else (f"?{a.node}" if a.node else "*")
            return f"COUNT(DISTINCT {arg})" if a.func == "count_distinct" else f"COUNT({arg})"
        return f"{a.func.upper()}({var(a.ref)})"
