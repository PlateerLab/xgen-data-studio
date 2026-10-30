"""Studio configuration file: the ontology, the backends to open, and what to project at start."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from xgen_data_studio.model import Ontology
from xgen_data_studio.studio import Studio

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _env(v: Any) -> Any:
    if isinstance(v, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), v)
    if isinstance(v, dict):
        return {k: _env(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_env(x) for x in v]
    return v


def open_backend(spec: dict, base: Path):
    kind = spec.get("kind")
    if kind == "sqlite":
        from xgen_data_studio.backends.sql import SqliteBackend

        path = spec.get("path", ":memory:")
        b = SqliteBackend(path if path == ":memory:" else str(base / path))
        if spec.get("seed"):
            b.script((base / spec["seed"]).read_text(encoding="utf-8"))
        return b
    if kind == "postgres":
        import psycopg

        from xgen_data_studio.backends.sql import DbApiBackend

        return DbApiBackend(psycopg.connect(spec["dsn"]), "postgres", paramstyle="format")
    if kind == "dbapi":
        import importlib

        from xgen_data_studio.backends.sql import DbApiBackend

        mod = importlib.import_module(spec["module"])
        conn = mod.connect(**spec.get("connect", {}))
        return DbApiBackend(conn, spec.get("dialect", "postgres"), paramstyle=spec.get("paramstyle", "format"))
    if kind == "rdflib":
        from xgen_data_studio.backends.rdf import RdflibBackend

        return RdflibBackend()
    if kind == "sparql":
        from xgen_data_studio.backends.rdf import SparqlEndpointBackend

        return SparqlEndpointBackend(spec["query_url"], update_url=spec.get("update_url", ""),
                                     gsp_url=spec.get("gsp_url", ""), user=spec.get("user", ""),
                                     password=spec.get("password", ""))
    if kind == "neo4j":
        import neo4j

        from xgen_data_studio.backends.graph import Neo4jBackend

        driver = neo4j.GraphDatabase.driver(spec["uri"], auth=(spec.get("user", "neo4j"), spec.get("password", "")))
        return Neo4jBackend(driver, database=spec.get("database"))
    raise ValueError(f"unknown backend kind '{kind}'")


def load_studio(path: str | Path) -> Studio:
    import yaml

    p = Path(path)
    spec = _env(yaml.safe_load(p.read_text(encoding="utf-8")))
    base = p.parent
    onto = Ontology.load(base / spec["ontology"]).check()
    now = None
    if spec.get("now"):
        fixed = datetime.fromisoformat(str(spec["now"]))
        now = lambda: fixed  # noqa: E731
    studio = Studio(onto, now=now, use_zen=bool(spec.get("zen", False)))
    for name, b in (spec.get("backends") or {}).items():
        studio.add_backend(name, open_backend(b, base), source=bool(b.get("source", False)))
    if spec.get("project"):
        studio.project(into=list(spec["project"]))
    return studio
