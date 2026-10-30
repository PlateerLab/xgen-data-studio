"""Agent-facing tools over a studio: describe, translate, query, decide, request actions. Scoped by role."""
from __future__ import annotations

import json
from typing import Any

from xgen_data_studio.actions import Actor
from xgen_data_studio.studio import Studio
from xgen_data_studio.values import normalize


def _jsonable(rows: list[tuple], columns: list[str], types: dict[str, str]) -> list[dict]:
    return [{c: normalize(v, types.get(c, "")) for c, v in zip(columns, r)} for r in rows]


class StudioTools:
    def __init__(self, studio: Studio, *, role: str | None = None, principal: dict | None = None,
                 actor_id: str = "agent", read_only: bool = False):
        self.studio, self.role, self.principal = studio, role, dict(principal or {})
        self.actor = Actor(actor_id, "agent", [role] if role else [])
        self.read_only = read_only

    def describe(self) -> dict:
        d = self.studio.describe()
        if self.role:
            r = self.studio.onto.roles[self.role]
            d["objects"] = {k: v for k, v in d["objects"].items() if r.can_read(k)}
            d["queries"] = {k: v for k, v in d["queries"].items() if r.can("run", k)}
            d["decisions"] = {k: v for k, v in d["decisions"].items() if r.can("run", k)}
            d["actions"] = {k: v for k, v in d["actions"].items() if r.can("request", k)}
        return d

    def translate(self, query: Any, to: str) -> dict:
        c = self.studio.translate(_query_arg(query), to)
        return {"language": c.language, "dialect": c.dialect, "text": c.text, "params": c.params,
                "literals": c.literals}

    def run_query(self, query: Any, params: dict | None = None, backend: str | None = None) -> dict:
        res = self.studio.run(_query_arg(query), params, backend=backend, role=self.role, principal=self.principal)
        return {"backend": res.backend, "columns": res.columns,
                "rows": _jsonable(res.rows, res.columns, res.compiled.column_types), "query_text": res.compiled.text}

    def run_sparql(self, text: str, backend: str | None = None) -> dict:
        from xgen_data_studio.parse.sparql import parse_sparql

        return self.run_query(parse_sparql(text, self.studio.onto), None, backend)

    def run_cypher(self, text: str, params: dict | None = None, backend: str | None = None) -> dict:
        from xgen_data_studio.parse.cypher import parse_cypher

        return self.run_query(parse_cypher(text, self.studio.onto), params, backend)

    def _visible(self, type_name: str, key: str) -> None:
        if not self.role:
            return
        k = self.studio.onto.obj(type_name).key
        q = {"match": {"x": type_name}, "where": {"eq": [f"x.{k}", str(key)]}, "return": [f"x.{k}"]}
        if not self.studio.run(q, role=self.role, principal=self.principal).rows:
            raise PermissionError(f"{type_name} {key} is outside this role's rows")

    def decide(self, decision: str, key: str, params: dict | None = None) -> dict:
        target = self.studio.onto.decisions[decision].target
        if target:
            self._visible(target, key)
        return self.studio.decide(decision, key, params, role=self.role).to_dict()

    def request_action(self, action: str, key: str, params: dict | None = None) -> dict:
        if self.read_only:
            raise PermissionError("this server is read-only")
        self._visible(self.studio.onto.actions[action].target, key)
        return self.studio.actions.request(action, key, params, actor=self.actor).to_dict()

    def list_proposals(self) -> list[dict]:
        return [p.to_dict() for p in self.studio.actions.proposals.values()]

    def list_backends(self) -> dict:
        return {n: b.capabilities.to_dict() for n, b in self.studio.backends.items()}


def _query_arg(query: Any) -> Any:
    if isinstance(query, str) and query.strip().startswith("{"):
        return json.loads(query)
    return query
