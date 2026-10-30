"""IR -> SQL/PGQ (ISO/IEC 9075-16 GRAPH_TABLE) and the CREATE PROPERTY GRAPH that declares the bound tables."""
from __future__ import annotations

from xgen_data_studio.check import aliases_of, find_prop
from xgen_data_studio.compile.base import Compiled, CompileError, Compiler, Params
from xgen_data_studio.compile.sql import qi
from xgen_data_studio.ir import And, Cmp, Contains, Edge, Exists, In, IsNull, Not, Or, Query, Ref
from xgen_data_studio.model import Ontology

_OP = {"eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def graph_ddl(onto: Ontology, graph: str = "") -> str:
    """CREATE PROPERTY GRAPH over the source tables: object types are vertices, bound links are edges."""
    graph = graph or onto.name.replace("-", "_")
    verts = []
    for o in onto.objects.values():
        if not o.table:
            continue
        props = ", ".join(f"{qi(p.col)} AS {qi(p.name)}" for p in o.properties.values())
        verts.append(f"  {qi(o.table)} AS {qi(o.name)} KEY ({qi(o.key_prop.col)}) LABEL {qi(o.name)} "
                     f"PROPERTIES ({props})")
    edges = []
    for lk in onto.links.values():
        src, dst = onto.objects[lk.source], onto.objects[lk.target]
        if not (src.table and dst.table):
            continue
        if lk.via:
            edges.append(f"  {qi(lk.via.table)} AS {qi(lk.name)} "
                         f"SOURCE KEY ({qi(lk.via.source_column)}) REFERENCES {qi(src.name)} ({qi(src.key_prop.col)}) "
                         f"DESTINATION KEY ({qi(lk.via.target_column)}) REFERENCES {qi(dst.name)} "
                         f"({qi(dst.key_prop.col)}) LABEL {qi(lk.name)} NO PROPERTIES")
        elif lk.on:
            sp, tp = src.prop(lk.on[0]), dst.prop(lk.on[1])
            if tp.name == dst.key:
                table, key = src, src.key_prop.col
                s_key, s_ref, d_key, d_ref = key, src.key_prop.col, sp.col, dst.key_prop.col
            elif sp.name == src.key:
                table, key = dst, dst.key_prop.col
                s_key, s_ref, d_key, d_ref = tp.col, src.key_prop.col, key, dst.key_prop.col
            else:
                continue
            edges.append(f"  {qi(table.table)} AS {qi(lk.name)} KEY ({qi(key)}) "
                         f"SOURCE KEY ({qi(s_key)}) REFERENCES {qi(src.name)} ({qi(s_ref)}) "
                         f"DESTINATION KEY ({qi(d_key)}) REFERENCES {qi(dst.name)} ({qi(d_ref)}) "
                         f"LABEL {qi(lk.name)} NO PROPERTIES")
    out = f"CREATE PROPERTY GRAPH {qi(graph)}\n VERTEX TABLES (\n" + ",\n".join(verts) + "\n )"
    if edges:
        out += "\n EDGE TABLES (\n" + ",\n".join(edges) + "\n )"
    return out


class PgqCompiler(Compiler):
    language = "sqlpgq"

    def __init__(self, onto: Ontology, dialect: str = "oracle", graph: str = ""):
        super().__init__(onto)
        self.dialect = dialect
        self.graph = graph or onto.name.replace("-", "_")

    def compile(self, q: Query | dict) -> Compiled:
        chk = self.checked(q)
        q = chk.query
        if any(e.optional for e in q.edges):
            raise CompileError("SQL/PGQ GRAPH_TABLE has no OPTIONAL MATCH; drop 'optional' or use another backend")
        self._types = aliases_of(q)
        self._params = Params(chk.param_types)
        self._n = 0
        pattern = self._pattern(q)
        where = f"\n  WHERE {self._filter(q.where)}" if q.where is not None else ""
        inner_cols, seen = [], {}
        outer, group = [], []
        for c in q.columns:
            e = c.expr
            if isinstance(e, Ref):
                inner_cols.append(f"{e.alias}.{qi(e.prop)} AS {qi(c.name)}")
                outer.append(f"gt.{qi(c.name)} AS {qi(c.name)}")
                group.append(f"gt.{qi(c.name)}")
                continue
            ref = e.ref
            if ref is None and e.node:
                ref = Ref(e.node, self.onto.obj(self._types[e.node]).key)
            if ref is None:
                outer.append(f"COUNT(*) AS {qi(c.name)}")
                continue
            col = seen.get(str(ref))
            if col is None:
                col = f"{ref.alias}__{ref.prop}"
                seen[str(ref)] = col
                inner_cols.append(f"{ref.alias}.{qi(ref.prop)} AS {qi(col)}")
            arg = f"gt.{qi(col)}"
            agg = f"COUNT(DISTINCT {arg})" if e.func == "count_distinct" else f"{e.func.upper()}({arg})"
            outer.append(f"{agg} AS {qi(c.name)}")
        lines = ["SELECT " + ("DISTINCT " if q.distinct else "") + ", ".join(outer),
                 f"FROM GRAPH_TABLE ({qi(self.graph)}",
                 f"  MATCH {pattern}{where}",
                 f"  COLUMNS ({', '.join(inner_cols)})", ") gt"]
        if q.aggregated and group:
            lines.append("GROUP BY " + ", ".join(group))
        if q.order:
            lines.append("ORDER BY " + ", ".join(f"{qi(o.name)} {'DESC' if o.desc else 'ASC'} NULLS LAST"
                                                  for o in q.order))
        if q.limit is not None:
            lines.append(f"FETCH FIRST {int(q.limit)} ROWS ONLY")
        return Compiled("sqlpgq", self.dialect, "\n".join(lines), "positional", list(self._params.order),
                        self._params.types, [c.name for c in q.columns], chk.column_types, self._params.literals)

    def _node(self, alias: str, seen: set[str]) -> str:
        if alias in seen:
            return f"({alias})"
        seen.add(alias)
        return f"({alias} IS {qi(self._types[alias])})"

    def _edge(self, e: Edge, seen: set[str]) -> str:
        self._n += 1
        rel = f"[e{self._n} IS {qi(e.link)}]"
        quant = f"{{{e.min_hops},{e.max_hops}}}" if e.hops else ""
        a, b = self._node(e.source, seen), self._node(e.target, seen)
        return f"{a}<-{rel}-{quant}{b}" if e.reverse else f"{a}-{rel}->{quant}{b}"

    def _pattern(self, q: Query) -> str:
        seen: set[str] = set()
        if not q.edges:
            return self._node(next(iter(q.nodes)), seen)
        return ", ".join(self._edge(e, seen) for e in q.edges)

    def _prop(self, ref: Ref) -> str:
        find_prop(self.onto, self._types[ref.alias], ref.prop)
        return f"{ref.alias}.{qi(ref.prop)}"

    def _ph(self, value, ref: Ref) -> str:
        p = find_prop(self.onto, self._types[ref.alias], ref.prop)
        self._params.add(value, p.type)
        return "?"

    def _filter(self, f) -> str:
        if isinstance(f, Cmp):
            rhs = self._prop(f.value) if isinstance(f.value, Ref) else self._ph(f.value, f.ref)
            return f"{self._prop(f.ref)} {_OP[f.op]} {rhs}"
        if isinstance(f, In):
            if not f.values:
                return "1 = 1" if f.negate else "1 = 0"
            marks = ", ".join(self._ph(v, f.ref) for v in f.values)
            return f"{self._prop(f.ref)} {'NOT IN' if f.negate else 'IN'} ({marks})"
        if isinstance(f, Contains):
            ph = self._ph(f.value, f.ref)
            return f"POSITION({ph} IN {self._prop(f.ref)}) > 0"
        if isinstance(f, IsNull):
            return f"{self._prop(f.ref)} IS {'NOT ' if f.negate else ''}NULL"
        if isinstance(f, And):
            return "(" + " AND ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Or):
            return "(" + " OR ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Not):
            return f"NOT ({self._filter(f.item)})"
        if isinstance(f, Exists):
            raise CompileError("SQL/PGQ GRAPH_TABLE has no EXISTS sub-pattern; use another backend")
        raise CompileError(f"cannot compile filter {f!r}")
