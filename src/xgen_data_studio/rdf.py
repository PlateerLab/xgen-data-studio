"""IRI scheme and RDF term syntax shared by the SPARQL compiler, the projection and the exporters."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from xgen_data_studio.model import Ontology

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
SH = "http://www.w3.org/ns/shacl#"
RR = "http://www.w3.org/ns/r2rml#"
RDF_TYPE = RDF + "type"

XSD_OF = {"string": "string", "enum": "string", "integer": "integer", "decimal": "decimal",
          "boolean": "boolean", "date": "date", "datetime": "dateTime"}
TYPE_OF_XSD = {"string": "string", "integer": "integer", "int": "integer", "long": "integer",
               "decimal": "decimal", "double": "decimal", "float": "decimal", "boolean": "boolean",
               "date": "date", "dateTime": "datetime"}


class Iris:
    def __init__(self, onto: Ontology):
        self.ns = onto.namespace

    def cls(self, type_name: str) -> str:
        return self.ns + type_name

    def prop(self, name: str) -> str:
        return self.ns + name

    def link(self, name: str) -> str:
        return self.ns + name

    def node(self, type_name: str, key: Any) -> str:
        return f"{self.ns}{type_name}/{quote(str(key), safe='')}"

    def key_of(self, iri: str) -> tuple[str, str] | None:
        if not iri.startswith(self.ns):
            return None
        rest = iri[len(self.ns):]
        if "/" not in rest:
            return None
        t, k = rest.split("/", 1)
        return t, unquote(k)

    def local(self, iri: str) -> str | None:
        return iri[len(self.ns):] if iri.startswith(self.ns) else None


def iri(s: str) -> str:
    return f"<{s}>"


def escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
            .replace("\t", "\\t"))


def literal(value: Any, type_: str, lang: str = "") -> str:
    """A Turtle/SPARQL literal of the ontology type."""
    if type_ == "boolean":
        return "true" if value else "false"
    if type_ == "integer":
        return str(int(value))
    if type_ in ("decimal", "date", "datetime"):
        return f'"{escape(str(value))}"^^<{XSD}{XSD_OF[type_]}>'
    s = f'"{escape(str(value))}"'
    return s + (f"@{lang}" if lang else "")


class Turtle:
    """A minimal Turtle writer: subject blocks with full IRIs and declared prefixes."""

    def __init__(self, prefixes: dict[str, str] | None = None):
        self.prefixes = dict(prefixes or {})
        self.blocks: list[str] = []

    def term(self, t: str) -> str:
        if t.startswith(("_:", '"', "(", "[")) or t in ("true", "false") or t[:1].isdigit() or t[:1] == "-":
            return t
        for p, ns in self.prefixes.items():
            if t.startswith(ns):
                rest = t[len(ns):]
                if rest and all(c.isalnum() or c in "_-" for c in rest) and not rest[0].isdigit():
                    return f"{p}:{rest}"
        return iri(t)

    def add(self, subject: str, pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        body = " ;\n    ".join(f"{self.term(p)} {self.term(o)}" for p, o in pairs)
        self.blocks.append(f"{self.term(subject)} {body} .")

    def text(self) -> str:
        head = "".join(f"@prefix {p}: <{ns}> .\n" for p, ns in self.prefixes.items())
        return head + "\n" + "\n\n".join(self.blocks) + "\n"


def bnode_list(items: list[str]) -> str:
    return "(" + " ".join(items) + ")"
