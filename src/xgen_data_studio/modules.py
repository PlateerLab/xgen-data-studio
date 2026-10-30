"""Ontology modules: domain knowledge packaged to plug into a composition and to unplug from it again."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xgen_data_studio.model import Ontology

KINDS = ("core", "domain", "industry", "customer", "binding")
SECTIONS = ("interfaces", "objects", "links", "decisions", "actions", "roles", "queries")
SINGULAR = {"interfaces": "interface", "objects": "object", "links": "link", "decisions": "decision",
            "actions": "action", "roles": "role", "queries": "query"}
_REQ = re.compile(r"^\s*([A-Za-z0-9_.-]+?)\s*(?:(@|>=|==)\s*([0-9][0-9A-Za-z.\-]*))?\s*$")


class ModuleError(ValueError):
    """Modules do not fit together: a missing requirement, a conflict, or a reference left dangling."""


def version_key(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v))


@dataclass(frozen=True)
class Requirement:
    name: str
    op: str = ""
    version: str = ""

    @classmethod
    def parse(cls, text: str) -> Requirement:
        m = _REQ.match(text)
        if not m:
            raise ModuleError(f"cannot read requirement '{text}'; write name, name@1.0.0 or name>=1.0")
        return cls(m.group(1), m.group(2) or "", m.group(3) or "")

    def allows(self, version: str) -> bool:
        if not self.op:
            return True
        if self.op in ("@", "=="):
            return version == self.version or version.startswith(self.version + ".")
        return version_key(version) >= version_key(self.version)

    def __str__(self) -> str:
        return f"{self.name}{self.op}{self.version}"


@dataclass
class Module:
    name: str
    version: str = "0.1.0"
    kind: str = "domain"
    label: str = ""
    description: str = ""
    namespace: str = ""
    requires: list[Requirement] = field(default_factory=list)
    body: dict[str, Any] = field(default_factory=dict)
    extend: dict[str, Any] = field(default_factory=dict)
    remove: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @classmethod
    def from_dict(cls, d: dict) -> Module:
        if d.get("kind", "domain") not in KINDS:
            raise ModuleError(f"module {d.get('module')}: kind must be one of {KINDS}")
        body = {s: copy.deepcopy(d.get(s) or {}) for s in SECTIONS}
        body["questions"] = copy.deepcopy(d.get("questions") or [])
        body["exclusive"] = copy.deepcopy(d.get("exclusive") or [])
        return cls(name=d["module"], version=str(d.get("version", "0.1.0")), kind=d.get("kind", "domain"),
                   label=d.get("label", ""), description=d.get("description", ""), namespace=d.get("namespace", ""),
                   requires=[Requirement.parse(r) for r in d.get("requires", [])], body=body,
                   extend=copy.deepcopy(d.get("extend") or {}), remove=copy.deepcopy(d.get("remove") or {}))

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"module": self.name, "version": self.version, "kind": self.kind}
        for k in ("label", "description", "namespace"):
            if getattr(self, k):
                out[k] = getattr(self, k)
        if self.requires:
            out["requires"] = [str(r) for r in self.requires]
        for s in (*SECTIONS, "questions", "exclusive"):
            if self.body.get(s):
                out[s] = copy.deepcopy(self.body[s])
        if self.extend:
            out["extend"] = copy.deepcopy(self.extend)
        if self.remove:
            out["remove"] = copy.deepcopy(self.remove)
        return out

    @classmethod
    def load(cls, path: str | Path) -> Module:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml

            return cls.from_dict(yaml.safe_load(text))
        return cls.from_dict(json.loads(text))

    def dump(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml

            p.write_text(yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def elements(self) -> list[str]:
        """Ids of what this module defines, extends or removes."""
        out = []
        for s in SECTIONS:
            for k, v in self.body.get(s, {}).items():
                out.append(f"{SINGULAR[s]}:{k}")
                if s == "objects":
                    out += [f"property:{k}.{p}" for p in (v.get("properties") or {})]
        for s, items in self.extend.items():
            for k, v in (items or {}).items():
                out.append(f"{SINGULAR.get(s, s)}:{k}")
                if s == "objects":
                    out += [f"property:{k}.{p}" for p in ((v or {}).get("properties") or {})]
        out += [f"question:{q['id']}" for q in self.body.get("questions", [])]
        return out

    def counts(self) -> dict[str, int]:
        c = {s: len(self.body.get(s, {})) for s in SECTIONS}
        c["properties"] = sum(len((v.get("properties") or {})) for v in self.body.get("objects", {}).values())
        c["questions"] = len(self.body.get("questions", []))
        c["extends"] = sum(len(v or {}) for v in self.extend.values())
        return c


@dataclass
class Composition:
    ontology: Ontology
    modules: list[Module]
    origin: dict[str, str]
    touched: dict[str, list[str]]
    removed: dict[str, str]
    issues: list[str]

    def owner(self, element: str) -> str:
        return self.origin.get(element, "")

    def by_module(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {m.name: [] for m in self.modules}
        for e, m in self.origin.items():
            out.setdefault(m, []).append(e)
        for e, ms in self.touched.items():
            for m in ms:
                out.setdefault(m, []).append(e)
        return {m: sorted(set(v)) for m, v in out.items()}

    def summary(self) -> list[dict]:
        rows = self.by_module()
        return [{"module": m.name, "version": m.version, "kind": m.kind, "label": m.label,
                 "requires": [str(r) for r in m.requires], "elements": len(rows.get(m.name, []))}
                for m in self.modules]


def order(modules: list[Module]) -> list[Module]:
    by = {}
    for m in modules:
        if m.name in by:
            raise ModuleError(f"module '{m.name}' is listed twice ({by[m.name].version}, {m.version})")
        by[m.name] = m
    for m in modules:
        for r in m.requires:
            dep = by.get(r.name)
            if dep is None:
                raise ModuleError(f"{m.key} requires '{r}', which is not attached")
            if not r.allows(dep.version):
                raise ModuleError(f"{m.key} requires '{r}', but {dep.key} is attached")
    out, state = [], {}

    def visit(m: Module, path: list[str]) -> None:
        if state.get(m.name) == "done":
            return
        if state.get(m.name) == "open":
            raise ModuleError(f"modules require each other in a cycle: {' -> '.join(path + [m.name])}")
        state[m.name] = "open"
        for r in m.requires:
            visit(by[r.name], path + [m.name])
        state[m.name] = "done"
        out.append(m)

    for m in modules:
        visit(m, [])
    return out


def _props_of(acc: dict, type_name: str) -> dict:
    """The property definitions a type sees, own first, then up its parent chain."""
    out, t, seen = {}, type_name, set()
    while t and t in acc["objects"] and t not in seen:
        seen.add(t)
        for k, v in (acc["objects"][t].get("properties") or {}).items():
            out.setdefault(k, v)
        t = acc["objects"][t].get("parent", "")
    return out


def _as_prop(v: Any) -> dict:
    return {"type": v} if isinstance(v, str) else dict(v or {})


def _extend_object(acc: dict, m: Module, name: str, patch: dict, touched: dict, origin: dict) -> None:
    obj = acc["objects"].get(name)
    if obj is None:
        raise ModuleError(f"{m.key} extends object type '{name}', which no attached module defines")
    for k in ("label", "description", "title", "parent", "cite"):
        if k in patch:
            obj[k] = patch[k]
    if "table" in patch or "source" in patch:
        obj["source"] = {"table": patch.get("table") or (patch.get("source") or {}).get("table", "")}
    for k in ("aligned", "implements"):
        if patch.get(k):
            obj[k] = list(dict.fromkeys(list(obj.get(k) or []) + list(patch[k])))
    props = obj.setdefault("properties", {})
    for p, pd in (patch.get("properties") or {}).items():
        pd = _as_prop(pd)
        if p in props:
            cur = _as_prop(props[p])
        elif p in _props_of(acc, name):
            cur = copy.deepcopy(_as_prop(_props_of(acc, name)[p]))
        else:
            if "type" not in pd and "values_add" not in pd:
                pd.setdefault("type", "string")
            cur = {}
            origin[f"property:{name}.{p}"] = m.name
        if "type" in pd and cur.get("type") and pd["type"] != cur["type"]:
            raise ModuleError(f"{m.key} changes the type of {name}.{p} from {cur['type']} to {pd['type']}")
        add = pd.pop("values_add", [])
        cur.update(pd)
        if add:
            cur["values"] = list(dict.fromkeys(list(cur.get("values") or []) + list(add)))
        props[p] = cur
        touched.setdefault(f"property:{name}.{p}", []).append(m.name)
    for p, col in (patch.get("columns") or {}).items():
        base = props.get(p)
        if base is None:
            inherited = _props_of(acc, name).get(p)
            if inherited is None:
                raise ModuleError(f"{m.key} binds {name}.{p}, which is not a property of {name}")
            base = copy.deepcopy(_as_prop(inherited))
        base = _as_prop(base)
        base["column"] = col
        props[p] = base
        touched.setdefault(f"property:{name}.{p}", []).append(m.name)
    if patch.get("transitions_add"):
        sm = obj.get("states")
        if not sm:
            raise ModuleError(f"{m.key} adds transitions to {name}, which has no state machine")
        sm["transitions"] = list(sm.get("transitions") or []) + list(patch["transitions_add"])
        for tr in patch["transitions_add"]:
            for s in (tr.get("from"), tr.get("to")):
                if s and s not in sm["states"]:
                    sm["states"].append(s)
    touched.setdefault(f"object:{name}", []).append(m.name)


def _extend_link(acc: dict, m: Module, name: str, patch: dict, touched: dict) -> None:
    lk = acc["links"].get(name)
    if lk is None:
        raise ModuleError(f"{m.key} extends link '{name}', which no attached module defines")
    for k in ("on", "via", "label", "description", "cite", "required", "inverse", "cardinality"):
        if k in patch:
            lk[k] = copy.deepcopy(patch[k])
    if True in patch:
        lk["on"] = copy.deepcopy(patch[True])
    if patch.get("aligned"):
        lk["aligned"] = list(dict.fromkeys(list(lk.get("aligned") or []) + list(patch["aligned"])))
    touched.setdefault(f"link:{name}", []).append(m.name)


def _extend_decision(acc: dict, m: Module, name: str, patch: dict, touched: dict) -> None:
    d = acc["decisions"].get(name)
    if d is None:
        raise ModuleError(f"{m.key} extends decision '{name}', which no attached module defines")
    d.setdefault("inputs", {}).update(copy.deepcopy(patch.get("inputs") or {}))
    d.setdefault("outputs", {}).update(copy.deepcopy(patch.get("outputs") or {}))
    rules = list(d.get("rules") or [])
    d["rules"] = copy.deepcopy(list(patch.get("rules_prepend") or [])) + rules + \
        copy.deepcopy(list(patch.get("rules_append") or []))
    for k in ("label", "cite", "hit_policy"):
        if k in patch:
            d[k] = patch[k]
    touched.setdefault(f"decision:{name}", []).append(m.name)


def _extend_role(acc: dict, m: Module, name: str, patch: dict, touched: dict) -> None:
    r = acc["roles"].get(name)
    if r is None:
        raise ModuleError(f"{m.key} extends role '{name}', which no attached module defines")
    for k in ("read", "run", "request", "execute"):
        if patch.get(k):
            r[k] = list(dict.fromkeys(list(r.get(k) or []) + list(patch[k])))
    if patch.get("row_filters"):
        r.setdefault("row_filters", {}).update(copy.deepcopy(patch["row_filters"]))
    touched.setdefault(f"role:{name}", []).append(m.name)


def compose(modules: list[Module], *, name: str = "", namespace: str = "", version: str = "",
            label: str = "") -> Composition:
    """Apply modules in requirement order: define, then extend, then remove; record who did what."""
    ordered = order(modules)
    acc: dict[str, Any] = {s: {} for s in SECTIONS}
    acc["questions"], acc["exclusive"] = [], []
    origin: dict[str, str] = {}
    touched: dict[str, list[str]] = {}
    removed: dict[str, str] = {}
    for m in ordered:
        for s in SECTIONS:
            for k, v in (m.body.get(s) or {}).items():
                eid = f"{SINGULAR[s]}:{k}"
                if k in acc[s]:
                    if acc[s][k] == v:
                        continue
                    raise ModuleError(f"{m.key} defines {SINGULAR[s]} '{k}', already defined by {origin[eid]}; "
                                      "extend it instead")
                acc[s][k] = copy.deepcopy(v)
                origin[eid] = m.name
                if s == "objects":
                    for p in (v.get("properties") or {}):
                        origin[f"property:{k}.{p}"] = m.name
        for q in m.body.get("questions") or []:
            acc["questions"].append(copy.deepcopy(q))
            origin[f"question:{q['id']}"] = m.name
        acc["exclusive"] += copy.deepcopy(m.body.get("exclusive") or [])
        for s, items in (m.extend or {}).items():
            for k, patch in (items or {}).items():
                if s == "objects":
                    _extend_object(acc, m, k, patch or {}, touched, origin)
                elif s == "links":
                    _extend_link(acc, m, k, patch or {}, touched)
                elif s == "decisions":
                    _extend_decision(acc, m, k, patch or {}, touched)
                elif s == "roles":
                    _extend_role(acc, m, k, patch or {}, touched)
                else:
                    raise ModuleError(f"{m.key}: cannot extend '{s}'; extend objects, links, decisions or roles")
        for s, items in (m.remove or {}).items():
            if s == "properties":
                for t, props in (items or {}).items():
                    for p in props:
                        if p not in (acc["objects"].get(t, {}).get("properties") or {}):
                            raise ModuleError(f"{m.key} removes {t}.{p}, which is not there")
                        del acc["objects"][t]["properties"][p]
                        removed[f"property:{t}.{p}"] = m.name
                continue
            if s == "questions":
                acc["questions"] = [q for q in acc["questions"] if q["id"] not in items]
                removed.update({f"question:{q}": m.name for q in items})
                continue
            if s not in SECTIONS:
                raise ModuleError(f"{m.key}: cannot remove '{s}'")
            for k in items:
                if k not in acc[s]:
                    raise ModuleError(f"{m.key} removes {SINGULAR[s]} '{k}', which is not there")
                del acc[s][k]
                removed[f"{SINGULAR[s]}:{k}"] = m.name
                if s == "objects":
                    for e in [e for e in origin if e.startswith(f"property:{k}.")]:
                        removed[e] = m.name
    namespace = namespace or next((m.namespace for m in reversed(ordered) if m.namespace), "")
    if not namespace:
        raise ModuleError("no namespace: give one, or set it on a module")
    domains = [m.name for m in ordered if m.kind == "domain"] or [m.name for m in ordered]
    d = {"ontology": name or "+".join(domains), "namespace": namespace,
         "version": version or " ".join(m.key for m in ordered),
         "label": label or " + ".join(m.label or m.name for m in ordered if m.kind in ("domain", "industry")), **acc}
    onto = Ontology.from_dict(d)
    for e in list(removed):
        origin.pop(e, None)
        touched.pop(e, None)
    return Composition(onto, ordered, origin, touched, removed, onto.validate())


@dataclass
class Impact:
    module: str
    dependents: list[str]
    removed: list[str]
    changed: list[str]
    broken: list[str]

    @property
    def ok(self) -> bool:
        return not self.broken

    def to_dict(self) -> dict:
        return {"module": self.module, "dependents": self.dependents, "removed": self.removed,
                "changed": self.changed, "broken": self.broken, "ok": self.ok}


def dependents_of(modules: list[Module], name: str) -> list[str]:
    out, frontier = [], {name}
    while frontier:
        nxt = {m.name for m in modules if m.name not in out and m.name not in frontier
               and any(r.name in frontier for r in m.requires)}
        out += sorted(nxt - set(out))
        frontier = nxt
    return out


def removal_impact(modules: list[Module], module: str, *, cascade: bool = False, **kw) -> Impact:
    """What unplugging a module takes away, and what it would leave pointing at nothing."""
    name = module
    if name not in {m.name for m in modules}:
        raise ModuleError(f"module '{name}' is not attached")
    deps = dependents_of(modules, name)
    full = compose(modules, **kw)
    gone = {name, *deps} if cascade or not deps else {name}
    rest = [m for m in modules if m.name not in gone]
    need = f"{', '.join(deps)} require {name}; detach them too (cascade) or keep {name}"
    try:
        reduced = compose(rest, **kw) if rest else None
    except ModuleError as e:
        return Impact(name, deps, [], [], ([need] if deps and not cascade else []) + [str(e)])
    if reduced is None:
        return Impact(name, deps, sorted(full.origin), [], [])
    removed = sorted(set(full.origin) - set(reduced.origin))
    changed = sorted(e for e, ms in full.touched.items() if gone & set(ms) and e not in removed)
    before = set(full.issues)
    broken = [i for i in reduced.issues if i not in before]
    if deps and not cascade:
        broken.insert(0, need)
    return Impact(name, deps, removed, changed, broken)
