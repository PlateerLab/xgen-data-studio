"""Studio: the ontology plus its backends; every read, decision and action goes through here."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from xgen_data_studio.actions import ActionService, SqlWriteback
from xgen_data_studio.backends.base import Backend, Result
from xgen_data_studio.check import all_props, check, column_of, find_prop
from xgen_data_studio.compile.base import Compiled, CompileError, compiler_for
from xgen_data_studio.conformance import ConformanceReport
from xgen_data_studio.conformance import run as run_conformance
from xgen_data_studio.decide.table import DecisionError, DecisionResult, Evidence, evaluate_table
from xgen_data_studio.ir import Cmp, Column, Edge, Query, Ref
from xgen_data_studio.model import Ontology
from xgen_data_studio.modules import Composition, Impact, Module, ModuleError, compose, removal_impact
from xgen_data_studio.projection import ChangeSet, Projection, apply_changes, load, project
from xgen_data_studio.roles import AccessDenied, apply_role
from xgen_data_studio.values import from_source, normalize, parse_datetime


@dataclass
class QuestionResult:
    id: str
    text: str
    passed: bool
    expected: Any
    got: Any
    error: str = ""


@dataclass
class QuestionReport:
    results: list[QuestionResult] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return sum(r.passed for r in self.results) / len(self.results) if self.results else 0.0

    def to_dict(self) -> dict:
        return {"accuracy": self.accuracy, "results": [asdict(r) for r in self.results]}


class Studio:
    def __init__(self, ontology: Ontology, *, now: Callable[[], datetime] | None = None, use_zen: bool = False):
        self.onto = ontology
        self.backends: dict[str, Backend] = {}
        self.source: str = ""
        self.now = now or datetime.now
        self.use_zen = use_zen
        self.actions = ActionService(self)
        self.projection: Projection | None = None
        self._loaded: dict[str, Projection] = {}
        self.composition: Composition | None = None
        self.library = None
        self._compose_kw: dict[str, str] = {}

    @classmethod
    def from_modules(cls, modules: list[Module], *, library=None, namespace: str = "", name: str = "",
                     **kw) -> Studio:
        """A studio over a composition of modules, which can then be attached and detached at run time."""
        comp = compose(modules, namespace=namespace, name=name)
        if comp.issues:
            raise ModuleError("; ".join(comp.issues))
        st = cls(comp.ontology, **kw)
        st.composition, st.library = comp, library
        st._compose_kw = {"namespace": comp.ontology.namespace, "name": name}
        return st

    @classmethod
    def from_library(cls, library, wanted: list[str], **kw) -> Studio:
        return cls.from_modules(library.resolve(wanted), library=library, **kw)

    def _modules(self) -> list[Module]:
        if self.composition is None:
            raise ModuleError("this studio was built from one ontology file, not from modules")
        return list(self.composition.modules)

    def _use(self, comp: Composition) -> Composition:
        if comp.issues:
            raise ModuleError("; ".join(comp.issues))
        self.composition, self.onto = comp, comp.ontology
        self.projection, self._loaded = None, {}
        return comp

    def attach(self, module: Module | str, version: str = "") -> Composition:
        """Plug a module in (with what it requires from the library); refused if the result does not hold."""
        current = self._modules()
        names = {m.name for m in current}
        if isinstance(module, str):
            if self.library is None:
                raise ModuleError("attach by name needs a library")
            wanted = [m.name for m in current]
            picked = self.library.resolve(wanted + [f"{module}@{version}" if version else module])
            extra = [m for m in picked if m.name not in names]
        else:
            extra = [module]
        if not extra:
            raise ModuleError(f"{module} is already attached")
        return self._use(compose(current + extra, **self._compose_kw))

    def detach(self, name: str, *, cascade: bool = False) -> Impact:
        """Unplug a module; refused, with the impact, when something left would point at what it took away."""
        current = self._modules()
        impact = removal_impact(current, name, cascade=cascade, **self._compose_kw)
        if not impact.ok:
            err = ModuleError("; ".join(impact.broken))
            err.impact = impact
            raise err
        gone = {name, *impact.dependents} if cascade else {name}
        self._use(compose([m for m in current if m.name not in gone], **self._compose_kw))
        return impact

    def detach_impact(self, name: str, *, cascade: bool = False) -> Impact:
        return removal_impact(self._modules(), name, cascade=cascade, **self._compose_kw)

    def check_bindings(self, *, backend: str | None = None, data: bool = True):
        from xgen_data_studio.bindings import check_bindings

        return check_bindings(self.onto, self.backend(backend), data=data)

    def add_backend(self, name: str, backend: Backend, *, source: bool = False) -> Backend:
        backend.name = name
        self.backends[name] = backend
        if source or (not self.source and backend.capabilities.language == "sql"):
            self.source = name
            if backend.capabilities.write and self.actions.writeback is None:
                self.actions.writeback = SqlWriteback(backend)
        return backend

    def backend(self, name: str | None = None) -> Backend:
        name = name or self.source or next(iter(self.backends), "")
        if name not in self.backends:
            raise KeyError(f"unknown backend '{name}'; have {sorted(self.backends)}")
        return self.backends[name]

    def query(self, q: Query | dict | str) -> Query:
        if isinstance(q, Query):
            return q
        if isinstance(q, str):
            rq = self.onto.queries.get(q)
            if rq is None:
                raise KeyError(f"unknown registered query '{q}'")
            return Query.from_dict(rq.query)
        return Query.from_dict(q)

    def translate(self, q: Query | dict | str, to: str) -> Compiled:
        return compiler_for(self.onto, to).compile(self.query(q))

    def run(self, q: Query | dict | str, params: dict | None = None, *, backend: str | None = None,
            role: str | None = None, principal: dict | None = None) -> Result:
        query = self.query(q)
        values = dict(params or {})
        if role:
            if isinstance(q, str) and not self.onto.roles[role].can("run", q):
                raise AccessDenied(f"role {role} may not run '{q}'")
            query, extra = apply_role(self.onto, query, role, principal)
            values.update(extra)
        b = self.backend(backend)
        missing = b.unsupported(query)
        if missing:
            raise CompileError(f"backend {b.name} does not support {missing}")
        compiled = b.compiler(self.onto).compile(query)
        return b.execute(compiled, values)

    def run_sparql(self, text: str, params: dict | None = None, **kw) -> Result:
        from xgen_data_studio.parse.sparql import parse_sparql

        return self.run(parse_sparql(text, self.onto), params, **kw)

    def run_cypher(self, text: str, params: dict | None = None, **kw) -> Result:
        from xgen_data_studio.parse.cypher import parse_cypher

        return self.run(parse_cypher(text, self.onto), params, **kw)

    def fetch(self, type_name: str, key: Any, *, backend: str | None = None) -> dict[str, Any] | None:
        obj = self.onto.obj(type_name)
        names = all_props(self.onto, type_name)
        q = Query(nodes={"x": type_name}, where=Cmp(Ref("x", obj.key), "eq", str(key)),
                  columns=[Column(Ref("x", p), p) for p in names])
        rows = self.run(q, backend=backend).rows
        if not rows:
            return None
        return {p: from_source(v, find_prop(self.onto, type_name, p).type) for p, v in zip(names, rows[0])}

    def _follow(self, type_name: str, key: Any, path: list[str]) -> tuple[str, list[str]]:
        nodes, edges, here = {"x0": type_name}, [], type_name
        for i, step in enumerate(path):
            lk = self.onto.links.get(step) or self.onto.link_by_inverse(step)
            if lk is None:
                raise DecisionError(f"unknown link '{step}'")
            here = lk.target if lk.name == step else lk.source
            nodes[f"x{i + 1}"] = here
            edges.append(Edge(f"x{i}", step, f"x{i + 1}"))
        last = f"x{len(path)}"
        q = Query(nodes=nodes, edges=edges, where=Cmp(Ref("x0", self.onto.obj(type_name).key), "eq", str(key)),
                  columns=[Column(Ref(last, self.onto.obj(here).key), "k")], distinct=True)
        return here, [str(r[0]) for r in self.run(q).rows]

    def decide(self, name: str, key: Any = None, params: dict | None = None, *, role: str | None = None,
               inputs: dict | None = None) -> DecisionResult:
        table = self.onto.decisions.get(name)
        if table is None:
            raise KeyError(f"unknown decision '{name}'")
        if role and not self.onto.roles[role].can("run", name):
            raise AccessDenied(f"role {role} may not run decision '{name}'")
        params = dict(params or {})
        values: dict[str, Any] = dict(inputs or {})
        evidence: list[Evidence] = []
        row = None
        if table.target and not inputs:
            row = self.fetch(table.target, key)
            if row is None:
                raise DecisionError(f"{table.target} {key} not found")
        for inp in ([] if inputs else table.inputs.values()):
            src = inp.source
            if "param" in src:
                values[inp.name] = params.get(src["param"])
                evidence.append(Evidence(inp.name, values[inp.name], source="parameter"))
                continue
            if "count" in src:
                _, keys = self._follow(table.target, key, list(src["count"]))
                values[inp.name] = len(keys)
                evidence.append(Evidence(inp.name, len(keys), table.target, str(key),
                                         "->".join(src["count"]), "count"))
                continue
            prop = src.get("property") or src.get("days_since")
            here, obj_key, obj_row = table.target, str(key), row
            if src.get("path"):
                here, keys = self._follow(table.target, key, list(src["path"]))
                if len(keys) > 1:
                    raise DecisionError(f"{name}.{inp.name}: the path reaches {len(keys)} objects; use count")
                obj_key = keys[0] if keys else ""
                obj_row = self.fetch(here, obj_key) if keys else None
            raw = obj_row.get(prop) if obj_row else None
            if "days_since" in src:
                value = None if raw is None else (self.now() - parse_datetime(raw)).days
            else:
                value = raw
            values[inp.name] = value
            obj = self.onto.obj(here)
            evidence.append(Evidence(inp.name, value, here, obj_key, prop,
                                     f"{obj.table}.{column_of(self.onto, here, prop)}" if obj.table else ""))
        if self.use_zen:
            from xgen_data_studio.decide.zen import evaluate_zen

            outputs, matched, notes, engine = evaluate_zen(table, values), [], [], "zen"
        else:
            outputs, matched, notes = evaluate_table(table, values)
            engine = "native"
        return DecisionResult(name, outputs, matched, values, evidence, notes, engine, table.target,
                              "" if key is None else str(key))

    def project(self, *, into: list[str] | None = None, source: str | None = None) -> dict[str, Any]:
        """Re-read the source and bring each graph backend up to date with a change set."""
        proj = project(self.onto, self.backend(source))
        self.projection = proj
        report: dict[str, Any] = {}
        targets = into if into is not None else [n for n, b in self.backends.items() if b.capabilities.load]
        for name in targets:
            b = self.backend(name)
            prev = self._loaded.get(name)
            if prev is None:
                load(self.onto, proj, b, clear=True)
                report[name] = {"loaded": {"nodes": len(proj.nodes), "edges": len(proj.edges)}}
            else:
                changes: ChangeSet = prev.diff(proj)
                apply_changes(self.onto, changes, b)
                report[name] = {"changes": changes.summary()}
            self._loaded[name] = proj
        return report

    def registered(self, params: dict[str, dict] | None = None) -> dict[str, tuple[Query, dict]]:
        params = params or {}
        defaults = _default_params(self.onto)
        return {n: (Query.from_dict(rq.query), params.get(n, defaults.get(n, {})))
                for n, rq in self.onto.queries.items()}

    def conformance(self, backends: list[str] | None = None, queries: dict | None = None) -> ConformanceReport:
        names = backends or list(self.backends)
        return run_conformance(self.onto, {n: self.backend(n) for n in names}, queries or self.registered())

    def questions(self, *, backend: str | None = None) -> QuestionReport:
        report = QuestionReport()
        for qs in self.onto.questions:
            try:
                if qs.decision:
                    res = self.decide(qs.decision, qs.key, qs.params)
                    got = res.outputs
                    passed = isinstance(got, dict) and all(got.get(k) == v for k, v in qs.expect.items())
                else:
                    res = self.run(qs.query, qs.params, backend=backend)
                    got, passed = _judge(qs.expect, res, check(self.query(qs.query), self.onto).column_types)
                report.results.append(QuestionResult(qs.id, qs.text, passed, qs.expect, got))
            except Exception as e:
                report.results.append(QuestionResult(qs.id, qs.text, False, qs.expect, None,
                                                     f"{type(e).__name__}: {e}"))
        return report

    def describe(self) -> dict:
        o = self.onto
        return {
            "ontology": o.name, "version": o.version, "label": o.label,
            "objects": {t.name: {"label": t.label, "key": t.key,
                                 "properties": {p.name: {"type": p.type, "label": p.label,
                                                         **({"values": p.values} if p.values else {})}
                                                for p in t.properties.values()}}
                        for t in o.objects.values()},
            "links": {lk.name: {"from": lk.source, "to": lk.target, "label": lk.label, "inverse": lk.inverse,
                                "cardinality": lk.cardinality} for lk in o.links.values()},
            "queries": {q.name: {"label": q.label, "params": q.params} for q in o.queries.values()},
            "decisions": {d.name: {"label": d.label, "target": d.target, "outputs": d.outputs}
                          for d in o.decisions.values()},
            "actions": {a.name: {"label": a.label, "target": a.target, "parameters": a.parameters,
                                 "approval": a.approval} for a in o.actions.values()},
            "backends": {n: b.capabilities.to_dict() for n, b in self.backends.items()},
        }

    def column(self, type_name: str, prop: str) -> str:
        obj = self.onto.obj(type_name)
        return f"{obj.table}.{find_prop(self.onto, type_name, prop).col}"


def _default_params(onto: Ontology) -> dict[str, dict]:
    out: dict[str, dict] = {n: dict(q.example) for n, q in onto.queries.items() if q.example}
    for qs in onto.questions:
        if qs.query and qs.query not in out:
            out[qs.query] = dict(qs.params)
    return out


def _judge(expect: Any, res: Result, types: dict[str, str]) -> tuple[Any, bool]:
    rows = [{c: normalize(v, types.get(c, "")) for c, v in zip(res.columns, r)} for r in res.rows]
    if not isinstance(expect, dict):
        return rows, rows == expect
    if "rows" in expect:
        return len(rows), len(rows) == expect["rows"]
    if "column" in expect:
        got = [r[expect["column"]] for r in rows]
        return got, got == [normalize(v) for v in expect["values"]]
    if "first" in expect:
        first = rows[0] if rows else {}
        return first, all(first.get(k) == normalize(v) for k, v in expect["first"].items())
    return rows, False
