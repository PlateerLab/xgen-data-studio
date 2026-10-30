"""What every compiler returns, and how its parameters get bound."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from xgen_data_studio.check import Checked, check
from xgen_data_studio.ir import Param, Query
from xgen_data_studio.model import Ontology
from xgen_data_studio.values import coerce


class CompileError(ValueError):
    """The query uses something this language or dialect cannot express."""


@dataclass
class Compiled:
    language: str
    dialect: str
    text: str
    style: str
    params: list[str]
    param_types: dict[str, str]
    columns: list[str]
    column_types: dict[str, str]
    literals: dict[str, Any] = field(default_factory=dict)
    render: Callable[[Any, str], str] | None = None

    def bind(self, values: dict[str, Any] | None = None) -> tuple[str, Any]:
        """Return (text, args) for the driver; inline style returns (text-with-literals, None)."""
        given = {**self.literals, **(values or {})}
        missing = [p for p in self.params if p not in given]
        if missing:
            raise CompileError(f"missing parameters {missing}")
        typed = {p: _coerce(given[p], self.param_types.get(p, "string")) for p in self.params}
        if self.style == "positional":
            return self.text, tuple(typed[p] for p in self.params)
        if self.style == "named":
            return self.text, typed
        text = self.text
        for p in self.params:
            text = text.replace(marker(p), self.render(typed[p], self.param_types.get(p, "string")))
        return text, None

    def preview(self, values: dict[str, Any] | None = None) -> str:
        """The query text with parameter values shown inline, for reading only."""
        from xgen_data_studio.rdf import literal

        text, args = self.bind(values)
        if args is None:
            return text
        if self.style == "named":
            for k in sorted(args, key=len, reverse=True):
                text = text.replace(f"${k}", _show(args[k], self.param_types.get(k, "string"), literal))
            return text
        out, i = [], 0
        for ch in text:
            if ch == "?" and i < len(args):
                out.append(_show(args[i], self.param_types.get(self.params[i], "string"), literal))
                i += 1
            else:
                out.append(ch)
        return "".join(out)


def _coerce(v: Any, t: str) -> Any:
    if isinstance(v, (list, tuple)):
        return [coerce(x, t) for x in v]
    return coerce(v, t)


def _show(v: Any, t: str, literal) -> str:
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_show(x, t, literal) for x in v) + "]"
    if v is None:
        return "NULL"
    if t in ("integer", "decimal", "boolean"):
        return literal(v, t) if t != "decimal" else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def marker(name: str) -> str:
    return f"$${name}$$"


class Params:
    """Collect parameters in use order; literals become generated parameters."""

    def __init__(self, declared_types: dict[str, str]):
        self.types = dict(declared_types)
        self.order: list[str] = []
        self.literals: dict[str, Any] = {}
        self._n = 0

    def add(self, value: Any, type_: str) -> str:
        if isinstance(value, Param):
            name = value.name
            self.types.setdefault(name, type_)
        else:
            self._n += 1
            name = f"_v{self._n}"
            self.literals[name] = value
            self.types[name] = type_
        self.order.append(name)
        return name


class Compiler:
    language = ""
    dialect = ""

    def __init__(self, onto: Ontology):
        self.onto = onto

    def checked(self, q: Query | dict) -> Checked:
        if isinstance(q, dict):
            q = Query.from_dict(q)
        return check(q, self.onto).raise_for_issues()

    def compile(self, q: Query | dict) -> Compiled:
        raise NotImplementedError


def compiler_for(onto: Ontology, language: str, dialect: str = "") -> Compiler:
    """Pick a compiler by language and dialect: sql[:dialect], cypher, gql, sparql, sqlpgq."""
    if ":" in language and not dialect:
        language, dialect = language.split(":", 1)
    language = language.lower()
    if language == "sql":
        from xgen_data_studio.compile.sql import SqlCompiler

        return SqlCompiler(onto, dialect or "postgres")
    if language == "cypher":
        from xgen_data_studio.compile.cypher import CypherCompiler

        return CypherCompiler(onto)
    if language == "gql":
        from xgen_data_studio.compile.cypher import GqlCompiler

        return GqlCompiler(onto)
    if language == "sparql":
        from xgen_data_studio.compile.sparql import SparqlCompiler

        return SparqlCompiler(onto)
    if language in ("sqlpgq", "pgq"):
        from xgen_data_studio.compile.pgq import PgqCompiler

        return PgqCompiler(onto, dialect or "oracle")
    raise CompileError(f"unknown language '{language}'; use sql, cypher, gql, sparql or sqlpgq")
