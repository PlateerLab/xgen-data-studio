"""Built-in rules over a projection: inverse, symmetric and transitive links derived; shapes checked."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field

from xgen_data_studio.model import Ontology
from xgen_data_studio.projection import EdgeKey, Projection


@dataclass
class DerivedEdge:
    link: str
    source_type: str
    source_key: str
    target_type: str
    target_key: str
    rule: str
    because: list[EdgeKey] = field(default_factory=list)

    @property
    def key(self) -> EdgeKey:
        return (self.link, self.source_type, self.source_key, self.target_type, self.target_key)


@dataclass
class Finding:
    kind: str
    type: str
    key: str
    detail: str


@dataclass
class RuleResult:
    derived: list[DerivedEdge] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def edges(self) -> set[EdgeKey]:
        return {d.key for d in self.derived}

    def to_dict(self) -> dict:
        return {"derived": [asdict(d) for d in self.derived], "findings": [asdict(f) for f in self.findings]}


def _is_a(onto: Ontology, t: str, base: str) -> bool:
    seen = set()
    while t and t not in seen:
        if t == base:
            return True
        seen.add(t)
        t = onto.objects[t].parent if t in onto.objects else ""
    return False


def run_rules(onto: Ontology, proj: Projection, *, max_depth: int = 5) -> RuleResult:
    res = RuleResult()
    base = set(proj.edges)
    seen = set(base)

    def add(d: DerivedEdge) -> None:
        if d.key not in seen:
            seen.add(d.key)
            res.derived.append(d)

    for lk in onto.links.values():
        mine = [e for e in base if e[0] == lk.name]
        if lk.transitive:
            out = defaultdict(set)
            for _, _, s, _, t in mine:
                out[s].add(t)
            for start in list(out):
                frontier, paths = {start}, {start: []}
                for _ in range(max_depth):
                    nxt = set()
                    for n in frontier:
                        for m in out.get(n, ()):
                            if m not in paths:
                                paths[m] = paths[n] + [(lk.name, lk.source, n, lk.target, m)]
                                nxt.add(m)
                    frontier = nxt
                    if not frontier:
                        break
                for m, path in paths.items():
                    if m != start and len(path) > 1:
                        add(DerivedEdge(lk.name, lk.source, start, lk.target, m, f"transitive:{lk.name}", path))
        if lk.symmetric:
            for e in mine:
                add(DerivedEdge(lk.name, e[3], e[4], e[1], e[2], f"symmetric:{lk.name}", [e]))
    for lk in onto.links.values():
        if lk.inverse:
            for e in [x for x in seen if x[0] == lk.name]:
                add(DerivedEdge(lk.inverse, e[3], e[4], e[1], e[2], f"inverse:{lk.name}", [e]))

    out_count: dict[tuple[str, str], int] = defaultdict(int)
    in_count: dict[tuple[str, str], int] = defaultdict(int)
    by_link: dict[str, set[str]] = defaultdict(set)
    for link, _, s, _, t in base:
        out_count[(link, s)] += 1
        in_count[(link, t)] += 1
        by_link[link].add(s)
    for lk in onto.links.values():
        for (t, k) in proj.nodes:
            if not _is_a(onto, t, lk.source):
                continue
            if lk.required and k not in by_link[lk.name]:
                res.findings.append(Finding("missing_link", t, k, f"has no '{lk.name}'"))
            if lk.cardinality in ("many_to_one", "one_to_one") and out_count[(lk.name, k)] > 1:
                res.findings.append(Finding("cardinality", t, k, f"'{lk.name}' has {out_count[(lk.name, k)]} targets"))
        if lk.cardinality in ("one_to_many", "one_to_one"):
            for (link, k), n in in_count.items():
                if link == lk.name and n > 1:
                    res.findings.append(Finding("cardinality", lk.target, k, f"is the target of {n} '{lk.name}'"))
    for a, b in onto.exclusive:
        for (t, k) in proj.nodes:
            if out_count[(a, k)] and out_count[(b, k)]:
                res.findings.append(Finding("exclusive", t, k, f"has both '{a}' and '{b}'"))
    for (t, k), props in proj.nodes.items():
        obj = onto.objects[t]
        for p in obj.properties.values():
            v = props.get(p.name)
            if p.required and v is None:
                res.findings.append(Finding("required", t, k, f"'{p.name}' is empty"))
            if p.type == "enum" and v is not None and p.values and v not in p.values:
                res.findings.append(Finding("enum", t, k, f"'{p.name}' = {v!r} is not one of {p.values}"))
        if obj.states:
            v = props.get(obj.states.property)
            if v is not None and v not in obj.states.states:
                res.findings.append(Finding("state", t, k, f"state {v!r} is not declared"))
    return res


def with_derived(proj: Projection, result: RuleResult) -> Projection:
    return Projection(dict(proj.nodes), set(proj.edges) | result.edges())
