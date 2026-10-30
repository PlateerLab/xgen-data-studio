"""Read a Cypher read query (MATCH / OPTIONAL MATCH / WHERE / RETURN / ORDER BY / LIMIT) into the query IR."""
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
    Param,
    Query,
    Ref,
)
from xgen_data_studio.model import Ontology
from xgen_data_studio.parse.sparql import ParseError

_TOKEN = re.compile(r"""
    \s*(?:
      (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
    | (?P<num>-?\d+(?:\.\d+)?)
    | (?P<param>\$[A-Za-z_][A-Za-z0-9_]*)
    | (?P<bq>`(?:[^`]|``)*`)
    | (?P<op><>|<=|>=|->|<-|\.\.|[=<>(){}\[\]:,.*\-|])
    | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )""", re.X)
_OPS = {"=": "eq", "<>": "ne", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte"}
_AGGS = {"count", "sum", "avg", "min", "max"}


def _tokens(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = text.strip().rstrip(";")
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                break
            raise ParseError(f"cannot read Cypher at: {text[pos:pos + 30]!r}")
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "bq":
            kind, val = "word", val[1:-1].replace("``", "`")
        elif kind == "word":
            kind = "kw" if val.upper() in _KEYWORDS else "word"
        out.append((kind, val))
        pos = m.end()
    return out


_KEYWORDS = {"MATCH", "OPTIONAL", "WHERE", "RETURN", "ORDER", "BY", "LIMIT", "AND", "OR", "NOT", "IS", "NULL",
             "AS", "DISTINCT", "DESC", "ASC", "CONTAINS", "IN", "EXISTS", "TRUE", "FALSE", "WITH", "ANY"}


class _Parser:
    def __init__(self, text: str, onto: Ontology):
        self.toks = _tokens(text)
        self.i = 0
        self.onto = onto
        self.nodes: dict[str, str] = {}
        self.edges: list[Edge] = []
        self._anon = 0

    def peek(self, k: int = 0) -> tuple[str, str]:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else ("eof", "")

    def kw(self, *words: str) -> bool:
        t = self.peek()
        return t[0] == "kw" and t[1].upper() in words

    def take(self, kind: str | None = None, value: str | None = None) -> str:
        t = self.peek()
        if kind and t[0] != kind and not (kind == "kw" and t[0] == "kw"):
            raise ParseError(f"expected {value or kind}, got {t[1] or 'end'}")
        if value and t[1].upper() != value.upper():
            raise ParseError(f"expected {value}, got {t[1] or 'end'}")
        self.i += 1
        return t[1]

    def name(self) -> str:
        k, v = self.peek()
        if k not in ("word", "kw"):
            raise ParseError(f"expected a name, got {v or 'end'}")
        self.i += 1
        return v

    def op(self, v: str) -> bool:
        if self.peek() == ("op", v):
            self.i += 1
            return True
        return False

    def node(self, scope: dict[str, str]) -> str:
        self.take("op", "(")
        if self.peek()[0] == "word":
            alias = self.take("word")
        else:
            self._anon += 1
            alias = f"_n{self._anon}"
        if self.op(":"):
            t = self.name()
            if t not in self.onto.objects:
                raise ParseError(f"unknown label '{t}'")
            prev = scope.get(alias)
            if prev and prev != t:
                raise ParseError(f"'{alias}' is labelled {prev} and {t}")
            scope[alias] = t
        elif alias not in scope:
            raise ParseError(f"give '{alias}' a label on first use")
        self.take("op", ")")
        return alias

    def rel(self) -> tuple[bool, str, int, int]:
        left = self.op("<-")
        if not left:
            self.take("op", "-")
        self.take("op", "[")
        if self.peek()[0] == "word" and self.peek(1) == ("op", ":"):
            self.i += 1
        self.take("op", ":")
        link = self.name()
        lo = hi = 1
        if self.op("*"):
            lo, hi = 1, MAX_HOPS
            if self.peek()[0] == "num":
                lo = hi = int(self.take("num"))
            if self.op(".."):
                hi = int(self.take("num")) if self.peek()[0] == "num" else MAX_HOPS
        self.take("op", "]")
        if left:
            self.take("op", "-")
        else:
            self.take("op", "->")
        return left, link, lo, hi

    def path(self, scope: dict[str, str], optional: bool, out: list[Edge]) -> None:
        self.kw("ANY") and self.take("kw")
        a = self.node(scope)
        while self.peek() in (("op", "-"), ("op", "<-")):
            left, link, lo, hi = self.rel()
            b = self.node(scope)
            out.append(Edge(b, link, a, optional, lo, hi) if left else Edge(a, link, b, optional, lo, hi))
            a = b

    def patterns(self, scope: dict[str, str], optional: bool, out: list[Edge]) -> None:
        self.path(scope, optional, out)
        while self.op(","):
            self.path(scope, optional, out)

    def ref(self, scope: dict[str, str]) -> Ref:
        a = self.take("word")
        if a not in scope:
            raise ParseError(f"unknown variable '{a}'")
        self.take("op", ".")
        return Ref(a, self.name())

    def literal(self) -> Any:
        k, v = self.peek()
        if k == "str":
            self.i += 1
            return bytes(v[1:-1], "utf-8").decode("unicode_escape") if "\\" in v else v[1:-1]
        if k == "num":
            self.i += 1
            return float(v) if "." in v else int(v)
        if k == "param":
            self.i += 1
            return Param(v[1:])
        if self.kw("TRUE", "FALSE"):
            return self.take("kw").upper() == "TRUE"
        if self.op("["):
            items = []
            if not self.op("]"):
                items.append(self.literal())
                while self.op(","):
                    items.append(self.literal())
                self.take("op", "]")
            return items
        raise ParseError(f"expected a value, got {v or 'end'}")

    def expr(self, scope) -> Any:
        items = [self.conj(scope)]
        while self.kw("OR"):
            self.take("kw")
            items.append(self.conj(scope))
        return items[0] if len(items) == 1 else Or(items)

    def conj(self, scope) -> Any:
        items = [self.neg(scope)]
        while self.kw("AND"):
            self.take("kw")
            items.append(self.neg(scope))
        return items[0] if len(items) == 1 else And(items)

    def neg(self, scope) -> Any:
        if self.kw("NOT"):
            self.take("kw")
            if self.kw("EXISTS"):
                ex = self.exists(scope)
                ex.negate = True
                return ex
            inner = self.neg(scope)
            if isinstance(inner, In):
                inner.negate = not inner.negate
                return inner
            return Not(inner)
        return self.atom(scope)

    def exists(self, scope) -> Exists:
        self.take("kw", "EXISTS")
        self.take("op", "{")
        if self.kw("MATCH"):
            self.take("kw")
        inner = dict(scope)
        edges: list[Edge] = []
        self.patterns(inner, False, edges)
        where = self.expr(inner) if self.kw("WHERE") and self.take("kw") else None
        self.take("op", "}")
        return Exists({a: t for a, t in inner.items() if a not in scope}, edges, where)

    def atom(self, scope) -> Any:
        if self.kw("EXISTS"):
            return self.exists(scope)
        if self.op("("):
            e = self.expr(scope)
            self.take("op", ")")
            return e
        ref = self.ref(scope)
        if self.kw("IS"):
            self.take("kw")
            neg = self.kw("NOT") and bool(self.take("kw"))
            self.take("kw", "NULL")
            return IsNull(ref, negate=neg)
        if self.kw("CONTAINS"):
            self.take("kw")
            return Contains(ref, self.literal())
        if self.kw("IN"):
            self.take("kw")
            vals = self.literal()
            if not isinstance(vals, list):
                raise ParseError("IN takes a literal list here")
            return In(ref, vals)
        k, v = self.peek()
        if k == "op" and v in _OPS:
            self.i += 1
            if self.peek()[0] == "word" and self.peek(1) == ("op", "."):
                return Cmp(ref, _OPS[v], self.ref(scope))
            return Cmp(ref, _OPS[v], self.literal())
        raise ParseError(f"expected a comparison after {ref}")

    def item(self) -> tuple[Ref | Agg, str]:
        k, v = self.peek()
        if k == "word" and v.lower() in _AGGS and self.peek(1) == ("op", "("):
            func = self.take("word").lower()
            self.take("op", "(")
            distinct = self.kw("DISTINCT") and bool(self.take("kw"))
            if self.op("*"):
                agg = Agg("count")
            elif self.peek(1) == ("op", "."):
                r = self.ref(self.nodes)
                agg = Agg("count_distinct" if distinct else func, r)
            else:
                a = self.take("word")
                if a not in self.nodes or func != "count":
                    raise ParseError(f"{func}({a}) needs a property")
                agg = Agg("count_distinct" if distinct else "count", node=a)
            self.take("op", ")")
            expr: Ref | Agg = agg
            default = func
        elif k == "word" and self.peek(1) == ("op", "."):
            expr = self.ref(self.nodes)
            default = expr.prop
        else:
            a = self.take("word")
            if a not in self.nodes:
                raise ParseError(f"unknown variable '{a}'")
            expr = Ref(a, self.onto.objects[self.nodes[a]].key)
            default = a
        name = self.name() if self.kw("AS") and self.take("kw") else default
        return expr, name

    def query(self) -> Query:
        where_parts = []
        while self.kw("MATCH", "OPTIONAL"):
            optional = self.kw("OPTIONAL") and bool(self.take("kw"))
            self.take("kw", "MATCH")
            self.patterns(self.nodes, optional, self.edges)
            if self.kw("WHERE"):
                self.take("kw")
                where_parts.append(self.expr(self.nodes))
            while self.kw("WITH"):
                self.take("kw")
                self.kw("DISTINCT") and self.take("kw")
                while not self.kw("WHERE", "MATCH", "OPTIONAL", "RETURN"):
                    self.i += 1
                if self.kw("WHERE"):
                    self.take("kw")
                    where_parts.append(self.expr(self.nodes))
        self.take("kw", "RETURN")
        distinct = self.kw("DISTINCT") and bool(self.take("kw"))
        cols = [self.item()]
        while self.op(","):
            cols.append(self.item())
        order = []
        if self.kw("ORDER"):
            self.take("kw")
            self.take("kw", "BY")
            names = {n for _, n in cols}
            while True:
                name = self.name()
                if self.kw("IS"):
                    self.take("kw")
                    self.take("kw", "NULL")
                    self.op(",")
                    continue
                if self.op("."):
                    prop = self.name()
                    name = next((n for e, n in cols if isinstance(e, Ref) and (e.alias, e.prop) == (name, prop)),
                                prop)
                desc = self.kw("DESC") and bool(self.take("kw"))
                self.kw("ASC") and self.take("kw")
                if name not in names:
                    raise ParseError(f"order by '{name}': order by a returned column")
                order.append(Order(name, desc))
                if not self.op(","):
                    break
        limit = None
        if self.kw("LIMIT"):
            self.take("kw")
            limit = int(self.take("num"))
        if self.peek()[0] != "eof":
            raise ParseError(f"unexpected '{self.peek()[1]}'")
        where = None
        if where_parts:
            where = where_parts[0] if len(where_parts) == 1 else And(where_parts)
        return Query(nodes=dict(self.nodes), edges=self.edges, where=where,
                     columns=[Column(e, n) for e, n in cols], order=order, limit=limit, distinct=distinct)


def parse_cypher(text: str, onto: Ontology) -> Query:
    return _Parser(text, onto).query()
