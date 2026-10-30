"""Write port: read source rows through the bindings, project them to nodes and edges, ship the change set."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from xgen_data_studio.check import all_props, find_prop
from xgen_data_studio.ir import Column, Edge, Query, Ref
from xgen_data_studio.model import Ontology
from xgen_data_studio.rdf import RDF_TYPE, Iris, iri, literal
from xgen_data_studio.values import from_source

NodeKey = tuple[str, str]
EdgeKey = tuple[str, str, str, str, str]


@dataclass
class Projection:
    nodes: dict[NodeKey, dict[str, Any]] = field(default_factory=dict)
    edges: set[EdgeKey] = field(default_factory=set)

    def ancestors(self, onto: Ontology, type_name: str) -> list[str]:
        out, t = [], type_name
        while t and t not in out:
            out.append(t)
            t = onto.objects[t].parent if t in onto.objects else ""
        return out

    def triples(self, onto: Ontology) -> list[tuple[str, str, str]]:
        """(subject, predicate, object) in N-Triples term syntax."""
        ir, out = Iris(onto), []
        for (t, k), props in sorted(self.nodes.items()):
            s = iri(ir.node(t, k))
            for a in self.ancestors(onto, t):
                out.append((s, iri(RDF_TYPE), iri(ir.cls(a))))
            for p, v in sorted(props.items()):
                if v is None:
                    continue
                ptype = onto.property_type(p) or "string"
                out.append((s, iri(ir.prop(p)), literal(v, ptype)))
        for link, st, sk, tt, tk in sorted(self.edges):
            out.append((iri(ir.node(st, sk)), iri(ir.link(link)), iri(ir.node(tt, tk))))
        return out

    def ntriples(self, onto: Ontology) -> str:
        return "".join(f"{s} {p} {o} .\n" for s, p, o in self.triples(onto))

    def turtle(self, onto: Ontology) -> str:
        return self.ntriples(onto)

    def cypher(self, onto: Ontology, batch: int = 500) -> list[tuple[str, dict]]:
        """MERGE statements (with $rows) that load this projection into a property graph."""
        stmts: list[tuple[str, dict]] = []
        by_type: dict[str, list[dict]] = {}
        for (t, k), props in sorted(self.nodes.items()):
            by_type.setdefault(t, []).append({"key": k, "props": {p: _graph_value(v) for p, v in props.items()}})
        for t, rows in by_type.items():
            key = onto.objects[t].key
            labels = ":".join(f"`{a}`" for a in self.ancestors(onto, t))
            for i in range(0, len(rows), batch):
                stmts.append((f"UNWIND $rows AS r MERGE (n:{labels} {{`{key}`: r.key}}) SET n += r.props",
                              {"rows": rows[i:i + batch]}))
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for link, st, sk, tt, tk in sorted(self.edges):
            groups.setdefault((link, st, tt), []).append({"s": sk, "t": tk})
        for (link, st, tt), rows in groups.items():
            sk, tk = onto.objects[st].key, onto.objects[tt].key
            for i in range(0, len(rows), batch):
                stmts.append((f"UNWIND $rows AS r MATCH (a:`{st}` {{`{sk}`: r.s}}), (b:`{tt}` {{`{tk}`: r.t}}) "
                              f"MERGE (a)-[:`{link}`]->(b)", {"rows": rows[i:i + batch]}))
        return stmts

    def diff(self, newer: Projection) -> ChangeSet:
        old, new = self.nodes, newer.nodes
        added = {k: new[k] for k in new.keys() - old.keys()}
        removed = {k: old[k] for k in old.keys() - new.keys()}
        changed = {k: (old[k], new[k]) for k in old.keys() & new.keys() if old[k] != new[k]}
        return ChangeSet(added, removed, changed, newer.edges - self.edges, self.edges - newer.edges)

    def to_dict(self) -> dict:
        return {"nodes": [{"type": t, "key": k, "props": {p: _graph_value(v) for p, v in v_.items()}}
                          for (t, k), v_ in sorted(self.nodes.items())],
                "edges": [list(e) for e in sorted(self.edges)]}


@dataclass
class ChangeSet:
    added: dict[NodeKey, dict]
    removed: dict[NodeKey, dict]
    changed: dict[NodeKey, tuple[dict, dict]]
    added_edges: set[EdgeKey]
    removed_edges: set[EdgeKey]

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.added_edges or self.removed_edges)

    def summary(self) -> dict[str, int]:
        return {"added": len(self.added), "removed": len(self.removed), "changed": len(self.changed),
                "added_edges": len(self.added_edges), "removed_edges": len(self.removed_edges)}

    def sparql_update(self, onto: Ontology) -> str:
        """DELETE DATA / INSERT DATA that moves a graph from the old projection to the new one."""
        old = Projection({**self.removed, **{k: v[0] for k, v in self.changed.items()}}, set(self.removed_edges))
        new = Projection({**self.added, **{k: v[1] for k, v in self.changed.items()}}, set(self.added_edges))
        parts = []
        dels = old.triples(onto)
        if dels:
            parts.append("DELETE DATA {\n" + "".join(f"  {s} {p} {o} .\n" for s, p, o in dels) + "}")
        ins = new.triples(onto)
        if ins:
            parts.append("INSERT DATA {\n" + "".join(f"  {s} {p} {o} .\n" for s, p, o in ins) + "}")
        return " ;\n".join(parts)

    def cypher(self, onto: Ontology) -> list[tuple[str, dict]]:
        stmts: list[tuple[str, dict]] = []
        for link, st, sk, tt, tk in sorted(self.removed_edges):
            stmts.append((f"MATCH (a:`{st}` {{`{onto.objects[st].key}`: $s}})-[r:`{link}`]->"
                          f"(b:`{tt}` {{`{onto.objects[tt].key}`: $t}}) DELETE r", {"s": sk, "t": tk}))
        for t, k in sorted(self.removed):
            stmts.append((f"MATCH (n:`{t}` {{`{onto.objects[t].key}`: $k}}) DETACH DELETE n", {"k": k}))
        for (t, k), (_, props) in sorted(self.changed.items()):
            stmts.append((f"MATCH (n:`{t}` {{`{onto.objects[t].key}`: $k}}) SET n = $props",
                          {"k": k, "props": {p: _graph_value(v) for p, v in props.items()}}))
        rest = Projection(dict(self.added), set(self.added_edges))
        return stmts + rest.cypher(onto)


def _graph_value(v: Any) -> Any:
    from decimal import Decimal

    return float(v) if isinstance(v, Decimal) else v


def _read_rows(onto: Ontology, source, q: Query) -> list[tuple]:
    compiled = source.compiler(onto).compile(q)
    return source.execute(compiled).rows


def project(onto: Ontology, source) -> Projection:
    """Read every bound object type and link from a relational source backend."""
    proj = Projection()
    for t in onto.objects.values():
        if not t.table:
            continue
        names = all_props(onto, t.name)
        types = {p: find_prop(onto, t.name, p).type for p in names}
        q = Query(nodes={"x": t.name}, columns=[Column(Ref("x", p), p) for p in names])
        for row in _read_rows(onto, source, q):
            props = {p: from_source(v, types[p]) for p, v in zip(names, row)}
            key = props.get(t.key)
            if key is None:
                continue
            for a in proj.ancestors(onto, t.name)[1:]:
                props.setdefault(onto.objects[a].key, key)
            proj.nodes[(t.name, str(key))] = props
    for lk in onto.links.values():
        src, dst = onto.objects[lk.source], onto.objects[lk.target]
        if not (lk.bound and src.table and dst.table):
            continue
        q = Query(nodes={"a": src.name, "b": dst.name}, edges=[Edge("a", lk.name, "b")],
                  columns=[Column(Ref("a", src.key), "s"), Column(Ref("b", dst.key), "t")])
        for s, t in _read_rows(onto, source, q):
            if s is not None and t is not None:
                proj.edges.add((lk.name, src.name, str(s), dst.name, str(t)))
    return proj


def turtle_to_insert(ttl: str) -> str:
    try:
        import rdflib
    except ImportError as e:
        raise ImportError("loading Turtle through SPARQL Update needs the [rdf] extra") from e
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    body = "".join(f"  {s.n3()} {p.n3()} {o.n3()} .\n" for s, p, o in g)
    return "INSERT DATA {\n" + body + "}"


def load(onto: Ontology, projection: Projection, backend, *, clear: bool = True) -> None:
    """Ship a whole projection into a graph backend (rdflib, SPARQL endpoint, Neo4j)."""
    if backend.capabilities.language == "sparql":
        backend.load_turtle(projection.ntriples(onto), clear=clear)
        return
    if backend.capabilities.language in ("cypher", "gql"):
        if clear:
            backend.run("MATCH (n) DETACH DELETE n")
        for text, params in projection.cypher(onto):
            backend.run(text, params)
        return
    raise ValueError(f"backend {backend.name} does not take projections")


def apply_changes(onto: Ontology, changes: ChangeSet, backend) -> None:
    if changes.empty:
        return
    if backend.capabilities.language == "sparql":
        backend.update(changes.sparql_update(onto))
        return
    if backend.capabilities.language in ("cypher", "gql"):
        for text, params in changes.cypher(onto):
            backend.run(text, params)
        return
    raise ValueError(f"backend {backend.name} does not take change sets")
