"""IR -> SQL over the bound source tables (joins, recursive CTEs), other dialects via sqlglot."""
from __future__ import annotations

from dataclasses import dataclass

from xgen_data_studio.check import aliases_of, find_prop
from xgen_data_studio.compile.base import Compiled, CompileError, Compiler, Params
from xgen_data_studio.ir import Agg, And, Cmp, Contains, Edge, Exists, In, IsNull, Not, Or, Query, Ref

NATIVE = ("postgres", "sqlite")
_OP = {"eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass
class _Step:
    table: str
    alias: str
    cond: str


class SqlCompiler(Compiler):
    language = "sql"

    def __init__(self, onto, dialect: str = "postgres"):
        super().__init__(onto)
        self.dialect = dialect
        self.native = dialect if dialect in NATIVE else "postgres"

    def compile(self, q: Query | dict) -> Compiled:
        chk = self.checked(q)
        q = chk.query
        self._types = aliases_of(q)
        self._params = Params(chk.param_types)
        self._ctes: list[str] = []
        self._n = 0
        sql = self._select(q)
        if self._ctes:
            sql = "WITH RECURSIVE " + ",\n".join(self._ctes) + "\n" + sql
        if self.dialect not in NATIVE:
            sql = _transpile(sql, self.dialect)
        return Compiled("sql", self.dialect, sql, "positional", list(self._params.order), self._params.types,
                        [c.name for c in q.columns], chk.column_types, self._params.literals)

    def _table(self, alias: str) -> str:
        obj = self.onto.obj(self._types[alias])
        if not obj.table:
            raise CompileError(f"{obj.name} has no source table")
        return qi(obj.table)

    def _col(self, ref: Ref) -> str:
        p = find_prop(self.onto, self._types[ref.alias], ref.prop)
        return f"t_{ref.alias}.{qi(p.col)}"

    def _key(self, alias: str) -> str:
        obj = self.onto.obj(self._types[alias])
        return f"t_{alias}.{qi(obj.key_prop.col)}"

    def _closure(self, lk, e: Edge) -> str:
        self._n += 1
        r, src = f"r_{self._n}", self.onto.obj(lk.source)
        if lk.via:
            base = (f"SELECT {qi(lk.via.source_column)} AS s, {qi(lk.via.target_column)} AS t "
                    f"FROM {qi(lk.via.table)}")
        elif lk.on:
            sp, tp = src.prop(lk.on[0]), src.prop(lk.on[1])
            key = qi(src.key_prop.col)
            base = (f"SELECT a.{key} AS s, b.{key} AS t FROM {qi(src.table)} a "
                    f"JOIN {qi(src.table)} b ON a.{qi(sp.col)} = b.{qi(tp.col)}")
        else:
            raise CompileError(f"link {lk.name} has no source binding (on/via)")
        self._ctes.append(f"{r}(s, t, d) AS (SELECT s, t, 1 FROM ({base}) b0 UNION ALL "
                          f"SELECT {r}.s, b1.t, {r}.d + 1 FROM {r} JOIN ({base}) b1 ON b1.s = {r}.t "
                          f"WHERE {r}.d < {e.max_hops})")
        return f"(SELECT DISTINCT s, t FROM {r} WHERE d >= {e.min_hops})"

    def _steps(self, e: Edge, known: str, new: str) -> list[_Step]:
        lk = self.onto.link(e.link)
        ls, lt = (e.target, e.source) if e.reverse else (e.source, e.target)
        known_is_source = known == ls
        if e.hops:
            self._n += 1
            c = f"c_{self._n}"
            closure = self._closure(lk, e)
            near, far = ("s", "t") if known_is_source else ("t", "s")
            return [_Step(closure, c, f"{c}.{near} = {self._key(known)}"),
                    _Step(self._table(new), f"t_{new}", f"{self._key(new)} = {c}.{far}")]
        if lk.via:
            self._n += 1
            j = f"j_{self._n}"
            sc, tc = qi(lk.via.source_column), qi(lk.via.target_column)
            near, far = (sc, tc) if known_is_source else (tc, sc)
            return [_Step(qi(lk.via.table), j, f"{j}.{near} = {self._key(known)}"),
                    _Step(self._table(new), f"t_{new}", f"{self._key(new)} = {j}.{far}")]
        if lk.on:
            return [_Step(self._table(new), f"t_{new}", self._on_cond(lk, ls, lt))]
        raise CompileError(f"link {lk.name} has no source binding (on/via)")

    def _on_cond(self, lk, ls: str, lt: str) -> str:
        return f"{self._col(Ref(ls, lk.on[0]))} = {self._col(Ref(lt, lk.on[1]))}"

    def _pattern(self, edges: list[Edge], known: set[str]) -> tuple[list[tuple[_Step, bool]], list[str]]:
        steps: list[tuple[_Step, bool]] = []
        extra: list[str] = []
        known = set(known)
        for e in edges:
            if e.source in known and e.target in known:
                lk = self.onto.link(e.link)
                if not lk.on or e.hops:
                    raise CompileError(f"a cycle through '{lk.name}' needs an 'on' link without hops")
                ls, lt = (e.target, e.source) if e.reverse else (e.source, e.target)
                extra.append(self._on_cond(lk, ls, lt))
                continue
            k, n = (e.source, e.target) if e.source in known else (e.target, e.source)
            steps += [(s, e.optional) for s in self._steps(e, k, n)]
            known.add(n)
        return steps, extra

    def _select(self, q: Query) -> str:
        root = next(iter(q.nodes))
        steps, extra = self._pattern(q.edges, {root})
        sql = [f"FROM {self._table(root)} t_{root}"]
        for s, opt in steps:
            sql.append(f"{'LEFT JOIN' if opt else 'JOIN'} {s.table} {s.alias} ON {s.cond}")
        conds = extra + ([self._filter(q.where)] if q.where is not None else [])
        cols, group = [], []
        for c in q.columns:
            if isinstance(c.expr, Ref):
                expr = self._col(c.expr)
                group.append(expr)
            else:
                expr = self._agg(c.expr)
            cols.append(f"{expr} AS {qi(c.name)}")
        head = "SELECT " + ("DISTINCT " if q.distinct else "") + ", ".join(cols)
        out = [head, *sql]
        if conds:
            out.append("WHERE " + " AND ".join(conds))
        if q.aggregated and group:
            out.append("GROUP BY " + ", ".join(group))
        if q.order:
            out.append("ORDER BY " + ", ".join(f"{qi(o.name)} {'DESC' if o.desc else 'ASC'} NULLS LAST"
                                              for o in q.order))
        if q.limit is not None:
            out.append(f"LIMIT {int(q.limit)}")
        return "\n".join(out)

    def _agg(self, a: Agg) -> str:
        if a.func in ("count", "count_distinct"):
            arg = self._col(a.ref) if a.ref is not None else (self._key(a.node) if a.node else "*")
            if a.func == "count_distinct":
                return f"COUNT(DISTINCT {arg})"
            return f"COUNT({arg})"
        return f"{a.func.upper()}({self._col(a.ref)})"

    def _ph(self, value, ref: Ref) -> str:
        p = find_prop(self.onto, self._types[ref.alias], ref.prop)
        self._params.add(value, p.type)
        return "?"

    def _filter(self, f) -> str:
        if isinstance(f, Cmp):
            rhs = self._col(f.value) if isinstance(f.value, Ref) else self._ph(f.value, f.ref)
            return f"{self._col(f.ref)} {_OP[f.op]} {rhs}"
        if isinstance(f, In):
            if not f.values:
                return "1 = 1" if f.negate else "1 = 0"
            marks = ", ".join(self._ph(v, f.ref) for v in f.values)
            return f"{self._col(f.ref)} {'NOT IN' if f.negate else 'IN'} ({marks})"
        if isinstance(f, Contains):
            col, ph = self._col(f.ref), self._ph(f.value, f.ref)
            if self.native == "sqlite":
                return f"instr({col}, {ph}) > 0"
            return f"strpos({col}, {ph}) > 0"
        if isinstance(f, IsNull):
            return f"{self._col(f.ref)} IS {'NOT ' if f.negate else ''}NULL"
        if isinstance(f, And):
            return "(" + " AND ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Or):
            return "(" + " OR ".join(self._filter(x) for x in f.items) + ")"
        if isinstance(f, Not):
            return f"NOT ({self._filter(f.item)})"
        if isinstance(f, Exists):
            return self._exists(f)
        raise CompileError(f"cannot compile filter {f!r}")

    def _exists(self, f: Exists) -> str:
        outer = set(self._types) - set(f.nodes)
        steps, extra = self._pattern(f.edges, outer)
        if not steps:
            raise CompileError("exists needs an edge to a new alias")
        first, rest = steps[0][0], steps[1:]
        parts = [f"SELECT 1 FROM {first.table} {first.alias}"]
        for s, opt in rest:
            parts.append(f"{'LEFT JOIN' if opt else 'JOIN'} {s.table} {s.alias} ON {s.cond}")
        conds = [first.cond, *extra]
        if f.where is not None:
            conds.append(self._filter(f.where))
        parts.append("WHERE " + " AND ".join(conds))
        return f"{'NOT ' if f.negate else ''}EXISTS ({' '.join(parts)})"


def _transpile(sql: str, dialect: str) -> str:
    try:
        import sqlglot
        from sqlglot.errors import ErrorLevel
    except ImportError as e:
        raise CompileError(f"SQL dialect '{dialect}' needs the [sql] extra (sqlglot)") from e
    try:
        return sqlglot.transpile(sql, read="postgres", write=dialect, unsupported_level=ErrorLevel.RAISE,
                                 pretty=True)[0]
    except sqlglot.errors.SqlglotError as e:
        raise CompileError(f"cannot translate to {dialect}: {e}") from e
    except ValueError as e:
        raise CompileError(f"unknown SQL dialect '{dialect}': {e}") from e
