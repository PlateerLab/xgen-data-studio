"""RDF backends: an in-process rdflib graph, or any SPARQL 1.1 endpoint over HTTP."""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from typing import Any

from xgen_data_studio.backends.base import Backend, Capabilities, Result
from xgen_data_studio.compile.base import Compiled


class RdflibBackend(Backend):
    def __init__(self, graph: Any = None, name: str = "rdflib"):
        try:
            import rdflib
        except ImportError as e:
            raise ImportError("RdflibBackend needs the [rdf] extra (rdflib)") from e
        self.graph = graph if graph is not None else rdflib.Graph()
        self.name = name
        self.capabilities = Capabilities("sparql", "1.1", load=True, reasoning=["owlrl"])

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        text, _ = compiled.bind(values)
        res = self.graph.query(text)
        rows = []
        for r in res:
            rows.append(tuple(_py(r[c]) if c in r.labels else None for c in compiled.columns))
        return Result(compiled.columns, rows, self.name, compiled)

    def load_turtle(self, ttl: str, *, clear: bool = False) -> None:
        if clear:
            self.graph.remove((None, None, None))
        self.graph.parse(data=ttl, format="turtle")

    def update(self, sparql_update: str) -> None:
        self.graph.update(sparql_update)


def _py(v: Any) -> Any:
    if v is None:
        return None
    return v.toPython() if hasattr(v, "toPython") else v


class SparqlEndpointBackend(Backend):
    """Fuseki, GraphDB, Stardog, Virtuoso, Oxigraph server, Neptune RDF: anything speaking SPARQL 1.1 over HTTP."""

    def __init__(self, query_url: str, *, update_url: str = "", gsp_url: str = "", user: str = "",
                 password: str = "", timeout: float = 60, name: str = "sparql"):
        self.query_url, self.update_url, self.gsp_url = query_url, update_url, gsp_url
        self.timeout = timeout
        self.name = name
        self._auth = ("Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()) if user else ""
        self.capabilities = Capabilities("sparql", "1.1", load=bool(update_url or gsp_url))

    def _post(self, url: str, body: bytes, ctype: str, accept: str = "") -> bytes:
        headers = {"Content-Type": ctype}
        if accept:
            headers["Accept"] = accept
        if self._auth:
            headers["Authorization"] = self._auth
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read()

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        text, _ = compiled.bind(values)
        raw = self._post(self.query_url, urllib.parse.urlencode({"query": text}).encode(),
                         "application/x-www-form-urlencoded", "application/sparql-results+json")
        data = json.loads(raw)
        rows = [tuple(_term(b.get(c)) for c in compiled.columns) for b in data["results"]["bindings"]]
        return Result(compiled.columns, rows, self.name, compiled)

    def load_turtle(self, ttl: str, *, clear: bool = False) -> None:
        if self.gsp_url:
            url = self.gsp_url + ("&" if "?" in self.gsp_url else "?") + "default"
            req = urllib.request.Request(url, data=ttl.encode(), method="PUT" if clear else "POST",
                                         headers={"Content-Type": "text/turtle",
                                                  **({"Authorization": self._auth} if self._auth else {})})
            with urllib.request.urlopen(req, timeout=self.timeout):
                return
        if not self.update_url:
            raise RuntimeError(f"{self.name}: no update or graph store URL to load into")
        from xgen_data_studio.projection import turtle_to_insert

        if clear:
            self.update("CLEAR DEFAULT")
        self.update(turtle_to_insert(ttl))

    def update(self, sparql_update: str) -> None:
        if not self.update_url:
            raise RuntimeError(f"{self.name}: no update URL")
        self._post(self.update_url, urllib.parse.urlencode({"update": sparql_update}).encode(),
                   "application/x-www-form-urlencoded")


_XSD = "http://www.w3.org/2001/XMLSchema#"


def _term(b: dict | None) -> Any:
    if b is None:
        return None
    v, dt = b.get("value"), b.get("datatype", "")
    if dt in (_XSD + "integer", _XSD + "int", _XSD + "long"):
        return int(v)
    if dt in (_XSD + "decimal", _XSD + "double", _XSD + "float"):
        return float(v)
    if dt == _XSD + "boolean":
        return v == "true"
    return v
