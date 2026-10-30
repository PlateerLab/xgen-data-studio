"""MCP server: the studio's tools for agents in any MCP client, over stdio or HTTP."""
from __future__ import annotations

import contextlib
import functools
import sys
from typing import Any

from xgen_data_studio.studio import Studio
from xgen_data_studio.tools import StudioTools

with contextlib.redirect_stdout(sys.stderr):
    try:
        import rdflib.plugins.sparql  # noqa: F401
    except ImportError:
        pass


def _server_class():
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError as e:
        raise ImportError("the MCP server needs the [mcp] extra") from e


def _tool_error():
    for mod in ("mcp.server.mcpserver.exceptions", "mcp.server.fastmcp.exceptions"):
        try:
            return __import__(mod, fromlist=["ToolError"]).ToolError
        except ImportError:
            continue
    return RuntimeError


def _guard(fn):
    err = _tool_error()

    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (PermissionError, KeyError, ValueError) as e:
            raise err(f"{type(e).__name__}: {e}") from e

    return run


def build_server(studio: Studio, *, role: str | None = None, principal: dict | None = None,
                 read_only: bool = False, name: str = "xgen-data-studio"):
    tools = StudioTools(studio, role=role, principal=principal, read_only=read_only)
    raw = _server_class()(name)

    class _Server:
        def tool(self):
            return lambda fn: raw.tool()(_guard(fn))

    server = _Server()

    @server.tool()
    def describe_ontology() -> dict:
        """Object types, properties, links, registered queries, decisions and actions this agent may use."""
        return tools.describe()

    @server.tool()
    def list_backends() -> dict:
        """Backends this studio can run queries on, with what each supports."""
        return tools.list_backends()

    @server.tool()
    def translate_query(query: Any, to: str) -> dict:
        """Show the backend text for a query (registered name or IR JSON); to = sql:<dialect>|cypher|gql|sparql|sqlpgq."""
        return tools.translate(query, to)

    @server.tool()
    def run_query(query: Any, params: dict | None = None, backend: str | None = None) -> dict:
        """Run a registered query by name, or an IR JSON object, on a backend (default: the source database)."""
        return tools.run_query(query, params, backend)

    @server.tool()
    def run_sparql(text: str, backend: str | None = None) -> dict:
        """Run a SPARQL SELECT written against the ontology on any backend, including SQL databases."""
        return tools.run_sparql(text, backend)

    @server.tool()
    def run_cypher(text: str, params: dict | None = None, backend: str | None = None) -> dict:
        """Run a Cypher read query written against the ontology on any backend, including SQL databases."""
        return tools.run_cypher(text, params, backend)

    @server.tool()
    def decide(decision: str, key: str, params: dict | None = None) -> dict:
        """Evaluate a decision table for one object; returns the outputs, the rule that matched and the evidence."""
        return tools.decide(decision, key, params)

    if not read_only:
        @server.tool()
        def request_action(action: str, key: str, params: dict | None = None) -> dict:
            """Request a declared action; checks run now, and a person approves it before anything is written."""
            return tools.request_action(action, key, params)

    @server.tool()
    def list_proposals() -> list[dict]:
        """Action requests and their status (pending, rejected, executed)."""
        return tools.list_proposals()

    return raw


def main(argv: list[str] | None = None) -> None:
    import argparse

    from xgen_data_studio.config import load_studio

    ap = argparse.ArgumentParser(prog="xds mcp")
    ap.add_argument("config")
    ap.add_argument("--role")
    ap.add_argument("--principal", action="append", default=[], help="key=value")
    ap.add_argument("--read-only", action="store_true")
    ap.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    a = ap.parse_args(argv)
    principal = dict(x.split("=", 1) for x in a.principal)
    server = build_server(load_studio(a.config), role=a.role, principal=principal, read_only=a.read_only)
    server.run(a.transport)
