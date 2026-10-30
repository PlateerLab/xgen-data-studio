"""Asset ontology: a graph of the data space itself, from tables and files to the agents that use them."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any

from xgen_data_studio.ir import Agg, Query, Ref, filter_refs
from xgen_data_studio.model import Ontology

KINDS = ("database", "table", "column", "folder", "file", "collection", "dataset", "object", "property", "link",
         "query", "decision", "action", "role", "agent", "tool", "workflow")
DEPENDS = ("uses", "mapsTo", "hasProperty", "canRead", "hasRole", "embeddedIn", "contains")


@dataclass
class Asset:
    id: str
    kind: str
    label: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relation:
    source: str
    kind: str
    target: str


class Catalog:
    def __init__(self) -> None:
        self.assets: dict[str, Asset] = {}
        self.relations: list[Relation] = []
        self._out: dict[str, list[Relation]] = defaultdict(list)
        self._in: dict[str, list[Relation]] = defaultdict(list)

    def add(self, id: str, kind: str, label: str = "", **attrs: Any) -> Asset:
        if kind not in KINDS:
            raise ValueError(f"unknown asset kind '{kind}'")
        a = self.assets.get(id)
        if a is None:
            a = self.assets[id] = Asset(id, kind, label or id.split(":", 1)[-1], dict(attrs))
        else:
            a.attrs.update(attrs)
        return a

    def relate(self, source: str, kind: str, target: str) -> None:
        r = Relation(source, kind, target)
        if r in self._out[source]:
            return
        self.relations.append(r)
        self._out[source].append(r)
        self._in[target].append(r)

    def add_folder(self, path: str, parent: str = "") -> str:
        fid = f"folder:{path}"
        self.add(fid, "folder", path.rstrip("/").rsplit("/", 1)[-1] or path)
        if parent:
            self.relate(f"folder:{parent}", "contains", fid)
        return fid

    def add_file(self, path: str, *, folder: str = "", collection: str = "", **attrs: Any) -> str:
        fid = f"file:{path}"
        self.add(fid, "file", path.rsplit("/", 1)[-1], **attrs)
        if folder:
            self.relate(f"folder:{folder}", "contains", fid)
        if collection:
            self.add(f"collection:{collection}", "collection", collection)
            self.relate(fid, "embeddedIn", f"collection:{collection}")
        return fid

    def add_agent(self, name: str, *, roles: list[str] = (), uses: list[str] = ()) -> str:
        aid = f"agent:{name}"
        self.add(aid, "agent", name)
        for r in roles:
            self.relate(aid, "hasRole", f"role:{r}")
        for u in uses:
            self.relate(aid, "uses", u)
        return aid

    def _walk(self, start: str, forward: bool) -> list[str]:
        seen, todo, out = {start}, deque([start]), []
        while todo:
            n = todo.popleft()
            edges = self._out[n] if forward else self._in[n]
            for r in edges:
                if r.kind not in DEPENDS:
                    continue
                nxt = r.target if forward else r.source
                if nxt not in seen:
                    seen.add(nxt)
                    out.append(nxt)
                    todo.append(nxt)
        return out

    def sees(self, agent: str) -> list[Asset]:
        """Everything an agent can reach through its roles and tools, down to tables, columns and files."""
        aid = agent if agent.startswith("agent:") else f"agent:{agent}"
        reach = set(self._walk(aid, forward=True))
        for c in [x for x in reach if x.startswith("collection:")]:
            reach |= {r.source for r in self._in[c] if r.kind == "embeddedIn"}
        return sorted((self.assets[x] for x in reach if x in self.assets), key=lambda a: (a.kind, a.id))

    def impact(self, asset_id: str) -> list[Asset]:
        """Everything that depends on an asset: properties, queries, decisions, actions, roles, agents."""
        seen, todo, out = {asset_id}, deque([asset_id]), []
        while todo:
            n = todo.popleft()
            for r in self._in[n]:
                if r.kind not in ("contains", "hasProperty") and r.kind in DEPENDS and r.source not in seen:
                    seen.add(r.source)
                    out.append(r.source)
                    todo.append(r.source)
        return sorted((self.assets[x] for x in out if x in self.assets), key=lambda a: (a.kind, a.id))

    def unused(self, kinds: tuple[str, ...] = ("table", "column", "file", "collection", "object")) -> list[Asset]:
        reached: set[str] = set()
        for a in self.assets.values():
            if a.kind in ("agent", "workflow"):
                reached |= {x.id for x in self.sees(a.id)} if a.kind == "agent" else set(self._walk(a.id, True))
        return sorted((a for a in self.assets.values() if a.kind in kinds and a.id not in reached),
                      key=lambda a: (a.kind, a.id))

    def to_dict(self) -> dict:
        return {"assets": [asdict(a) for a in self.assets.values()],
                "relations": [asdict(r) for r in self.relations]}


def _query_refs(onto: Ontology, q: Query) -> set[tuple[str, str]]:
    from xgen_data_studio.check import aliases_of

    types = aliases_of(q)
    refs = list(filter_refs(q.where))
    for c in q.columns:
        if isinstance(c.expr, Ref):
            refs.append(c.expr)
        elif isinstance(c.expr, Agg) and c.expr.ref is not None:
            refs.append(c.expr.ref)
    out = {(types[r.alias], r.prop) for r in refs if r.alias in types}
    out |= {(t, onto.objects[t].key) for t in types.values() if t in onto.objects}
    return out


def from_ontology(onto: Ontology, *, database: str = "source", catalog: Catalog | None = None) -> Catalog:
    """Assets and dependencies implied by the definition: bindings, queries, decisions, actions, roles."""
    cat = catalog or Catalog()
    db = f"database:{database}"
    cat.add(db, "database", database)
    for o in onto.objects.values():
        oid = f"object:{o.name}"
        cat.add(oid, "object", o.label or o.name)
        if o.table:
            tid = f"table:{o.table}"
            cat.add(tid, "table", o.table)
            cat.relate(db, "contains", tid)
            cat.relate(oid, "mapsTo", tid)
        for p in o.properties.values():
            pid = f"property:{o.name}.{p.name}"
            cat.add(pid, "property", p.label or p.name, type=p.type)
            cat.relate(oid, "hasProperty", pid)
            if o.table:
                cid = f"column:{o.table}.{p.col}"
                cat.add(cid, "column", f"{o.table}.{p.col}")
                cat.relate(f"table:{o.table}", "contains", cid)
                cat.relate(pid, "mapsTo", cid)
    for lk in onto.links.values():
        lid = f"link:{lk.name}"
        cat.add(lid, "link", lk.label or lk.name)
        cat.relate(lid, "uses", f"object:{lk.source}")
        cat.relate(lid, "uses", f"object:{lk.target}")
        if lk.on:
            cat.relate(lid, "uses", f"property:{lk.source}.{lk.on[0]}")
            cat.relate(lid, "uses", f"property:{lk.target}.{lk.on[1]}")
        if lk.via:
            tid = f"table:{lk.via.table}"
            cat.add(tid, "table", lk.via.table)
            cat.relate(db, "contains", tid)
            for col in (lk.via.source_column, lk.via.target_column):
                cid = f"column:{lk.via.table}.{col}"
                cat.add(cid, "column", f"{lk.via.table}.{col}")
                cat.relate(tid, "contains", cid)
                cat.relate(lid, "mapsTo", cid)
    for rq in onto.queries.values():
        qid = f"query:{rq.name}"
        cat.add(qid, "query", rq.label or rq.name)
        q = Query.from_dict(rq.query)
        for t, p in sorted(_query_refs(onto, q)):
            cat.relate(qid, "uses", f"property:{t}.{p}")
        for e in q.edges:
            lk = onto.links.get(e.link) or onto.link_by_inverse(e.link)
            if lk:
                cat.relate(qid, "uses", f"link:{lk.name}")
    for d in onto.decisions.values():
        did = f"decision:{d.name}"
        cat.add(did, "decision", d.label or d.name)
        for inp in d.inputs.values():
            src, here = inp.source, d.target
            for step in src.get("path", []) + list(src.get("count", [])):
                lk = onto.links.get(step) or onto.link_by_inverse(step)
                if lk:
                    cat.relate(did, "uses", f"link:{lk.name}")
                    here = lk.target if lk.name == step else lk.source
            prop = src.get("property") or src.get("days_since")
            if prop and here:
                cat.relate(did, "uses", f"property:{here}.{prop}")
    for a in onto.actions.values():
        aid = f"action:{a.name}"
        cat.add(aid, "action", a.label or a.name)
        for c in a.criteria:
            if c.decision:
                cat.relate(aid, "uses", f"decision:{c.decision}")
        obj = onto.objects.get(a.target)
        changed = list(a.set) + ([obj.states.property] if a.transition_to and obj and obj.states else [])
        for p in changed:
            cat.relate(aid, "uses", f"property:{a.target}.{p}")
    for r in onto.roles.values():
        rid = f"role:{r.name}"
        cat.add(rid, "role", r.label or r.name)
        for t in (list(onto.objects) if "*" in r.read else r.read):
            cat.relate(rid, "canRead", f"object:{t}")
        for verb in ("run", "request", "execute"):
            for n in getattr(r, verb):
                if n == "*":
                    continue
                kind = "query" if n in onto.queries else "decision" if n in onto.decisions else "action"
                cat.relate(rid, "uses", f"{kind}:{n}")
    return cat
