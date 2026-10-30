"""Property-graph backends (Neo4j and friends), and a callable adapter for engines without a driver here."""
from __future__ import annotations

from typing import Any, Callable

from xgen_data_studio.backends.base import Backend, Capabilities, Result
from xgen_data_studio.compile.base import Compiled


class Neo4jBackend(Backend):
    """Neo4j through the official driver; Memgraph and Neptune openCypher accept the same text."""

    def __init__(self, driver: Any, *, database: str | None = None, name: str = "neo4j"):
        self.driver = driver
        self.database = database
        self.name = name
        self.capabilities = Capabilities("cypher", "neo4j", load=True)

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        text, args = compiled.bind(values)
        records = self.run(text, args)
        return Result(compiled.columns, [tuple(r.get(c) for c in compiled.columns) for r in records],
                      self.name, compiled)

    def run(self, text: str, params: dict | None = None) -> list[dict]:
        kw = {"database_": self.database} if self.database else {}
        res = self.driver.execute_query(text, params or {}, **kw)
        records = res.records if hasattr(res, "records") else res[0]
        return [r.data() if hasattr(r, "data") else dict(r) for r in records]


class CallableBackend(Backend):
    """Wrap any engine: fn(text, args) -> list of row tuples (or dicts) in column order."""

    def __init__(self, name: str, capabilities: Capabilities, fn: Callable[[str, Any], list]):
        self.name = name
        self.capabilities = capabilities
        self.fn = fn

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        text, args = compiled.bind(values)
        rows = []
        for r in self.fn(text, args):
            rows.append(tuple(r.get(c) for c in compiled.columns) if isinstance(r, dict) else tuple(r))
        return Result(compiled.columns, rows, self.name, compiled)
