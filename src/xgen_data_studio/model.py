"""Domain ontology metamodel: one definition, bound to source tables, read by every adapter."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TYPES = ("string", "integer", "decimal", "boolean", "date", "datetime", "enum")
CARDINALITIES = ("one_to_one", "one_to_many", "many_to_one", "many_to_many")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ModelError(ValueError):
    """The ontology definition is inconsistent."""


@dataclass
class Property:
    name: str
    type: str = "string"
    label: str = ""
    description: str = ""
    column: str = ""
    unit: str = ""
    values: list[str] = field(default_factory=list)
    required: bool = False

    @property
    def col(self) -> str:
        return self.column or self.name


@dataclass
class Transition:
    source: str
    target: str
    action: str = ""


@dataclass
class StateMachine:
    property: str
    states: list[str]
    initial: str = ""
    transitions: list[Transition] = field(default_factory=list)

    def allows(self, source: str | None, target: str) -> bool:
        return any(t.source == source and t.target == target for t in self.transitions)


@dataclass
class ObjectType:
    name: str
    key: str
    properties: dict[str, Property]
    label: str = ""
    description: str = ""
    table: str = ""
    title: str = ""
    parent: str = ""
    implements: list[str] = field(default_factory=list)
    states: StateMachine | None = None

    def prop(self, name: str) -> Property:
        try:
            return self.properties[name]
        except KeyError:
            raise ModelError(f"{self.name} has no property '{name}'") from None

    @property
    def key_prop(self) -> Property:
        return self.prop(self.key)


@dataclass
class Via:
    table: str
    source_column: str
    target_column: str


@dataclass
class LinkType:
    name: str
    source: str
    target: str
    cardinality: str = "many_to_many"
    on: tuple[str, str] | None = None
    via: Via | None = None
    label: str = ""
    description: str = ""
    inverse: str = ""
    transitive: bool = False
    symmetric: bool = False
    required: bool = False

    @property
    def bound(self) -> bool:
        return self.on is not None or self.via is not None


@dataclass
class Interface:
    name: str
    properties: list[str]
    label: str = ""


@dataclass
class DecisionInput:
    name: str
    type: str
    source: dict[str, Any]


@dataclass
class DecisionRule:
    when: dict[str, str]
    then: dict[str, Any]
    id: str = ""
    note: str = ""


@dataclass
class DecisionTable:
    name: str
    inputs: dict[str, DecisionInput]
    outputs: dict[str, str]
    rules: list[DecisionRule]
    target: str = ""
    label: str = ""
    hit_policy: str = "first"


@dataclass
class Criterion:
    decision: str = ""
    expect: dict[str, Any] = field(default_factory=dict)
    states: list[str] = field(default_factory=list)


@dataclass
class ActionType:
    name: str
    target: str
    label: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)
    set: dict[str, Any] = field(default_factory=dict)
    transition_to: str = ""
    approval: bool = True


@dataclass
class Role:
    name: str
    label: str = ""
    read: list[str] = field(default_factory=list)
    row_filters: dict[str, dict] = field(default_factory=dict)
    run: list[str] = field(default_factory=list)
    request: list[str] = field(default_factory=list)
    execute: list[str] = field(default_factory=list)

    def can_read(self, type_name: str) -> bool:
        return "*" in self.read or type_name in self.read

    def can(self, verb: str, name: str) -> bool:
        names = getattr(self, verb)
        return "*" in names or name in names


@dataclass
class RegisteredQuery:
    name: str
    query: dict
    label: str = ""
    description: str = ""
    params: dict[str, str] = field(default_factory=dict)
    example: dict[str, Any] = field(default_factory=dict)


@dataclass
class Question:
    id: str
    text: str
    expect: Any
    query: str = ""
    decision: str = ""
    key: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Ontology:
    name: str
    namespace: str
    objects: dict[str, ObjectType]
    links: dict[str, LinkType] = field(default_factory=dict)
    version: str = "0.1.0"
    label: str = ""
    interfaces: dict[str, Interface] = field(default_factory=dict)
    decisions: dict[str, DecisionTable] = field(default_factory=dict)
    actions: dict[str, ActionType] = field(default_factory=dict)
    roles: dict[str, Role] = field(default_factory=dict)
    queries: dict[str, RegisteredQuery] = field(default_factory=dict)
    questions: list[Question] = field(default_factory=list)
    exclusive: list[tuple[str, str]] = field(default_factory=list)

    def obj(self, name: str) -> ObjectType:
        try:
            return self.objects[name]
        except KeyError:
            raise ModelError(f"unknown object type '{name}'") from None

    def link(self, name: str) -> LinkType:
        try:
            return self.links[name]
        except KeyError:
            raise ModelError(f"unknown link '{name}'") from None

    def link_by_inverse(self, name: str) -> LinkType | None:
        return next((lk for lk in self.links.values() if lk.inverse == name), None)

    def property_type(self, name: str) -> str | None:
        for o in self.objects.values():
            if name in o.properties:
                return o.properties[name].type
        return None

    def validate(self) -> list[str]:
        from xgen_data_studio.validate import validate_ontology

        return validate_ontology(self)

    def check(self) -> Ontology:
        issues = self.validate()
        if issues:
            raise ModelError("; ".join(issues))
        return self

    @classmethod
    def from_dict(cls, d: dict) -> Ontology:
        return _from_dict(d)

    def to_dict(self) -> dict:
        return _to_dict(self)

    @classmethod
    def load(cls, path: str | Path) -> Ontology:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as e:
                raise ImportError("YAML ontologies need the [yaml] extra (PyYAML)") from e
            return cls.from_dict(yaml.safe_load(text))
        return cls.from_dict(json.loads(text))

    def dump(self, path: str | Path) -> None:
        p = Path(path)
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml

            p.write_text(yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def _prop(name: str, d: Any) -> Property:
    if isinstance(d, str):
        d = {"type": d}
    return Property(name=name, type=d.get("type", "string"), label=d.get("label", ""),
                    description=d.get("description", ""), column=d.get("column", ""), unit=d.get("unit", ""),
                    values=list(d.get("values", [])), required=bool(d.get("required", False)))


def _states(d: dict | None) -> StateMachine | None:
    if not d:
        return None
    return StateMachine(property=d["property"], states=list(d.get("states", [])), initial=d.get("initial", ""),
                        transitions=[Transition(t["from"], t["to"], t.get("action", ""))
                                     for t in d.get("transitions", [])])


def _object(name: str, d: dict) -> ObjectType:
    source = d.get("source") or {}
    return ObjectType(name=name, key=d["key"], properties={k: _prop(k, v) for k, v in d.get("properties", {}).items()},
                      label=d.get("label", ""), description=d.get("description", ""),
                      table=source.get("table", d.get("table", "")), title=d.get("title", ""),
                      parent=d.get("parent", ""), implements=list(d.get("implements", [])),
                      states=_states(d.get("states")))


def _link(name: str, d: dict) -> LinkType:
    on = d.get("on", d.get(True))
    if isinstance(on, dict):
        if len(on) != 1:
            raise ModelError(f"link {name}: 'on' takes exactly one source: target pair")
        on = next(iter(on.items()))
    via = d.get("via")
    return LinkType(name=name, source=d["from"], target=d["to"], cardinality=d.get("cardinality", "many_to_many"),
                    on=tuple(on) if on else None,
                    via=Via(via["table"], via["source"], via["target"]) if via else None,
                    label=d.get("label", ""), description=d.get("description", ""), inverse=d.get("inverse", ""),
                    transitive=bool(d.get("transitive", False)), symmetric=bool(d.get("symmetric", False)),
                    required=bool(d.get("required", False)))


def _decision(name: str, d: dict) -> DecisionTable:
    inputs = {}
    for k, v in d.get("inputs", {}).items():
        v = dict(v)
        inputs[k] = DecisionInput(name=k, type=v.pop("type", "string"), source=v)
    rules = [DecisionRule(when={k: str(x) for k, x in (r.get("when") or {}).items()}, then=dict(r.get("then") or {}),
                          id=r.get("id", f"r{i + 1}"), note=r.get("note", ""))
             for i, r in enumerate(d.get("rules", []))]
    return DecisionTable(name=name, inputs=inputs, outputs=dict(d.get("outputs", {})), rules=rules,
                         target=d.get("target", ""), label=d.get("label", ""),
                         hit_policy=d.get("hit_policy", "first"))


def _action(name: str, d: dict) -> ActionType:
    crit = [Criterion(decision=c.get("decision", ""), expect=dict(c.get("expect", {})),
                      states=list(c.get("states", []))) for c in d.get("criteria", [])]
    return ActionType(name=name, target=d["target"], label=d.get("label", ""), parameters=dict(d.get("parameters", {})),
                      criteria=crit, set=dict(d.get("set", {})), transition_to=d.get("transition_to", ""),
                      approval=bool(d.get("approval", True)))


def _role(name: str, d: dict) -> Role:
    return Role(name=name, label=d.get("label", ""), read=list(d.get("read", [])),
                row_filters=dict(d.get("row_filters", {})), run=list(d.get("run", [])),
                request=list(d.get("request", [])), execute=list(d.get("execute", [])))


def _from_dict(d: dict) -> Ontology:
    return Ontology(
        name=d.get("ontology") or d.get("name") or "ontology",
        namespace=d["namespace"],
        version=str(d.get("version", "0.1.0")),
        label=d.get("label", ""),
        objects={k: _object(k, v) for k, v in d.get("objects", {}).items()},
        links={k: _link(k, v) for k, v in d.get("links", {}).items()},
        interfaces={k: Interface(k, list(v.get("properties", [])), v.get("label", ""))
                    for k, v in d.get("interfaces", {}).items()},
        decisions={k: _decision(k, v) for k, v in d.get("decisions", {}).items()},
        actions={k: _action(k, v) for k, v in d.get("actions", {}).items()},
        roles={k: _role(k, v) for k, v in d.get("roles", {}).items()},
        queries={k: RegisteredQuery(k, v["query"], v.get("label", ""), v.get("description", ""),
                                    dict(v.get("params", {})), dict(v.get("example", {})))
                 for k, v in d.get("queries", {}).items()},
        questions=[Question(id=q["id"], text=q["text"], expect=q.get("expect"), query=q.get("query", ""),
                            decision=q.get("decision", ""), key=str(q.get("key", "")),
                            params=dict(q.get("params", {}))) for q in d.get("questions", [])],
        exclusive=[tuple(x) for x in d.get("exclusive", [])],
    )


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in ("", [], {}, None, False)}


def _to_dict(o: Ontology) -> dict:
    objects = {}
    for t in o.objects.values():
        props = {p.name: _clean({"type": p.type, "label": p.label, "description": p.description,
                                 "column": p.column, "unit": p.unit, "values": p.values, "required": p.required})
                 for p in t.properties.values()}
        sm = None
        if t.states:
            sm = _clean({"property": t.states.property, "states": t.states.states, "initial": t.states.initial,
                         "transitions": [_clean({"from": x.source, "to": x.target, "action": x.action})
                                         for x in t.states.transitions]})
        objects[t.name] = _clean({"label": t.label, "description": t.description,
                                  "source": {"table": t.table} if t.table else None, "key": t.key, "title": t.title,
                                  "parent": t.parent, "implements": t.implements, "properties": props, "states": sm})
    links = {lk.name: _clean({"from": lk.source, "to": lk.target, "cardinality": lk.cardinality,
                              "on": {lk.on[0]: lk.on[1]} if lk.on else None,
                              "via": {"table": lk.via.table, "source": lk.via.source_column,
                                      "target": lk.via.target_column} if lk.via else None,
                              "label": lk.label, "description": lk.description, "inverse": lk.inverse,
                              "transitive": lk.transitive, "symmetric": lk.symmetric, "required": lk.required})
             for lk in o.links.values()}
    decisions = {}
    for dt in o.decisions.values():
        decisions[dt.name] = _clean({
            "label": dt.label, "target": dt.target, "hit_policy": dt.hit_policy,
            "inputs": {i.name: {"type": i.type, **i.source} for i in dt.inputs.values()},
            "outputs": dt.outputs,
            "rules": [_clean({"id": r.id, "when": r.when, "then": r.then, "note": r.note}) for r in dt.rules]})
    actions = {a.name: _clean({"label": a.label, "target": a.target, "parameters": a.parameters,
                               "criteria": [_clean({"decision": c.decision, "expect": c.expect, "states": c.states})
                                            for c in a.criteria],
                               "set": a.set, "transition_to": a.transition_to})
               | {"approval": a.approval} for a in o.actions.values()}
    roles = {r.name: _clean({"label": r.label, "read": r.read, "row_filters": r.row_filters, "run": r.run,
                             "request": r.request, "execute": r.execute}) for r in o.roles.values()}
    queries = {q.name: _clean({"label": q.label, "description": q.description, "params": q.params,
                               "example": q.example, "query": q.query}) for q in o.queries.values()}
    questions = [_clean({"id": q.id, "text": q.text, "query": q.query, "decision": q.decision, "key": q.key,
                         "params": q.params}) | {"expect": q.expect} for q in o.questions]
    return _clean({
        "ontology": o.name, "namespace": o.namespace, "version": o.version, "label": o.label,
        "objects": objects, "links": links,
        "interfaces": {i.name: _clean({"label": i.label, "properties": i.properties}) for i in o.interfaces.values()},
        "decisions": decisions, "actions": actions, "roles": roles, "queries": queries, "questions": questions,
        "exclusive": [list(x) for x in o.exclusive],
    })
