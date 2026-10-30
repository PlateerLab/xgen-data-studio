"""Backend port: what a backend can do, how it compiles, and how it runs a compiled query."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from xgen_data_studio.compile.base import Compiled, Compiler, compiler_for
from xgen_data_studio.model import Ontology


@dataclass
class Capabilities:
    language: str
    dialect: str = ""
    optional: bool = True
    exists: bool = True
    hops: bool = True
    contains: bool = True
    aggregates: bool = True
    load: bool = False
    write: bool = False
    reasoning: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Result:
    columns: list[str]
    rows: list[tuple]
    backend: str = ""
    compiled: Compiled | None = None

    def records(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r)) for r in self.rows]


class Backend:
    name = ""
    capabilities = Capabilities("sql")

    def compiler(self, onto: Ontology) -> Compiler:
        return compiler_for(onto, self.capabilities.language, self.capabilities.dialect)

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        raise NotImplementedError

    def unsupported(self, query) -> list[str]:
        """Features the query uses that this backend does not declare."""
        from xgen_data_studio.ir import Contains, Exists, walk_filters

        caps, out = self.capabilities, []
        if not caps.optional and any(e.optional for e in query.edges):
            out.append("optional")
        if not caps.hops and any(e.hops for e in query.edges):
            out.append("hops")
        kinds = {type(f) for f in walk_filters(query.where)}
        if not caps.exists and Exists in kinds:
            out.append("exists")
        if not caps.contains and Contains in kinds:
            out.append("contains")
        if not caps.aggregates and query.aggregated:
            out.append("aggregates")
        return out
