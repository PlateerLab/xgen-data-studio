"""IR -> Cypher 25 / openCypher, and ISO GQL as a dialect of the same pattern compiler."""
from __future__ import annotations

from xgen_data_studio.check import aliases_of, find_prop
from xgen_data_studio.compile.base import Compiled, CompileError, Compiler, Params
from xgen_data_studio.ir import Agg, And, Cmp, Contains, Edge, Exists, In, IsNull, Not, Or, Query, Ref

_OP = {"eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def bq(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


class CypherCompiler(Compiler):
    language = "cypher"
    dialect = "neo4j"
    gql = False

    def compile(self, q: Query | dict) -> Compiled:
        chk = self.checked(q)
        q = chk.query
        self._types = aliases_of(q)
        self._params = Params(chk.param_types)
        lines = self._match(q)
        if q.where is not None:
            cond = self._filter(q.where)
            if any(e.optional for e in q.edges):
                lines += [f"FILTER {cond}"] if self.gql else ["WITH *", f"WHERE {cond}"]
            else:
                lines.append(f"WHERE {cond}")
        lines += self._return(q)
        names = list(dict.fromkeys(self._params.order))
        return Compiled(self.language, self.dialect, "\n".join(lines), "named", names, self._params.types,
                        [c.name for c in q.columns], chk.column_types, self._params.literals)

    def _node(self, alias: str, seen: set[str]) -> str:
        if alias in seen:
            return f"({alias})"
        seen.add(alias)
        return f"({alias}:{bq(self._types[alias])})"

    def _hops(self, e: Edge) -> tuple[str, str]:
        if not e.hops:
            return "", ""
        if self.gql:
            return "", f"{{{e.min_hops},{e.max_hops}}}"
        return f"*{e.min_hops}..{e.max_hops}", ""

    def _edge(self, e: Edge, seen: set[str]) -> str:
        star, quant = self._hops(e)
        rel = f"[:{bq(e.link)}{star}]"
        a, b = self._node(e.source, seen), self._node(e.target, seen)
        body = f"{a}<-{rel}-{quant}{b}" if e.reverse else f"{a}-{rel}->{quant}{b}"
        return f"ANY {body}" if self.gql and e.hops else body

    def _match(self, q: Query) -> list[str]:
        seen: set[str] = set()
        root = next(iter(q.nodes))
        required = [self._edge(e, seen) for e in q.edges if not e.optional]
        if not required:
            required = [self._node(root, seen)]
        lines = ["MATCH " + ", ".join(required)]
        if not self.gql and any(e.hops for e in q.edges):
            lines.append("WITH DISTINCT " + ", ".join(sorted(seen)))
        for e in q.edges:
            if e.optional:
                lines.append("OPTIONAL MATCH " + self._edge(e, seen))
        return lines

    def _prop(self, ref: Ref) -> str:
        find_prop(self.onto, self._types[ref.alias], ref.prop)
        return f"{ref.alias}.{bq(ref.prop)}"

    def _ph(self, value, ref: Ref) -> str:
        p = find_prop(self.onto, self._types[ref.alias], ref.prop)
        return "$" + self._params.add(value, p.type)

    def _filter(self, f) -> str:
        if isinstance(f, Cmp):
            rhs = self._prop(f.value) if isinstance(f.value, Ref) else self._ph(f.value, f.ref)
            return f"{self._prop(f.ref)} {_OP[f.op]} {rhs}"
        if isinstance(f, In):
            p = find_prop(self.onto, self._types[f.ref.alias], f.ref.prop)
            name = self._params.add(list(f.values), p.type)
            self._params.types[name] = p.type
            expr = f"{self._prop(f.ref)} IN ${name}"
            return f"NOT ({expr})" if f.negate else expr
        if isinstance(f, Contains):
            if self.gql:
                raise CompileError("ISO GQL has no substring predicate; register a backend query for it")
            return f"{self._prop(f.ref)} CONTAINS {self._ph(f.value, f.ref)}"
        if isinstance(f, IsNull):
            return f"{self._prop(f.ref)} IS {'NOT ' if f.negate else ''}NULL"
        if isinstance(f, And):
            return "(" + " AND ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Or):
            return "(" + " OR ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Not):
            return f"NOT ({self._filter(f.item)})"
        if isinstance(f, Exists):
            seen = set(self._types) - set(f.nodes)
            pats = ", ".join(self._edge(e, seen) for e in f.edges)
            body = f"MATCH {pats}" + (f" WHERE {self._filter(f.where)}" if f.where is not None else "")
            return f"{'NOT ' if f.negate else ''}EXISTS {{ {body} }}"
        raise CompileError(f"cannot compile filter {f!r}")

    def _agg(self, a: Agg) -> str:
        if a.func in ("count", "count_distinct"):
            arg = self._prop(a.ref) if a.ref is not None else (a.node or "*")
            return f"count(DISTINCT {arg})" if a.func == "count_distinct" else f"count({arg})"
        return f"{a.func}({self._prop(a.ref)})"

    def _return(self, q: Query) -> list[str]:
        items, keys = [], []
        for c in q.columns:
            if isinstance(c.expr, Ref):
                items.append(f"{self._prop(c.expr)} AS {bq(c.name)}")
                keys.append(bq(c.name))
            else:
                items.append(f"{self._agg(c.expr)} AS {bq(c.name)}")
        line = "RETURN " + ("DISTINCT " if q.distinct else "") + ", ".join(items)
        if self.gql and q.aggregated and keys:
            line += " GROUP BY " + ", ".join(keys)
        out = [line]
        if q.order:
            if self.gql:
                out.append("ORDER BY " + ", ".join(f"{bq(o.name)} {'DESC' if o.desc else 'ASC'} NULLS LAST"
                                                  for o in q.order))
            else:
                out.append("ORDER BY " + ", ".join(f"{bq(o.name)} IS NULL, {bq(o.name)}{' DESC' if o.desc else ''}"
                                                  for o in q.order))
        if q.limit is not None:
            out.append(f"LIMIT {int(q.limit)}")
        return out


class GqlCompiler(CypherCompiler):
    language = "gql"
    dialect = "iso"
    gql = True
