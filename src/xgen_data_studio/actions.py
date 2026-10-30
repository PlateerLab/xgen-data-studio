"""Actions: checked requests, human approval, write-back to the source, and an audit trail."""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from typing import Any

from xgen_data_studio.compile.sql import qi
from xgen_data_studio.values import coerce


@dataclass
class Actor:
    id: str
    kind: str = "human"
    roles: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Proposal:
    id: str
    action: str
    target: str
    key: str
    params: dict[str, Any]
    requested_by: Actor
    status: str
    checks: list[CheckResult]
    changes: dict[str, Any]
    before: dict[str, Any] = field(default_factory=dict)
    approved_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditEntry:
    at: str
    actor: str
    actor_kind: str
    event: str
    action: str
    target: str
    key: str
    proposal: str
    detail: dict[str, Any] = field(default_factory=dict)


class SqlWriteback:
    """Apply an action's changes to the bound source table with one UPDATE."""

    def __init__(self, backend):
        self.backend = backend

    def apply(self, onto, type_name: str, key: str, changes: dict[str, Any]) -> int:
        obj = onto.obj(type_name)
        sets = ", ".join(f"{qi(obj.prop(p).col)} = ?" for p in changes)
        args = tuple(coerce(v, obj.prop(p).type) for p, v in changes.items()) + (key,)
        sql = f"UPDATE {qi(obj.table)} SET {sets} WHERE {qi(obj.key_prop.col)} = ?"
        return self.backend.run(sql, args)


class ActionService:
    def __init__(self, studio, writeback=None):
        self.studio = studio
        self.writeback = writeback
        self.proposals: dict[str, Proposal] = {}
        self.audit: list[AuditEntry] = []
        self._ids = itertools.count(1)

    def _log(self, actor: Actor, event: str, p: Proposal, **detail) -> None:
        self.audit.append(AuditEntry(self.studio.now().isoformat(timespec="seconds"), actor.id, actor.kind, event,
                                     p.action, p.target, p.key, p.id, detail))

    def _allowed(self, actor: Actor, verb: str, action: str) -> bool:
        roles = [self.studio.onto.roles[r] for r in actor.roles if r in self.studio.onto.roles]
        return any(r.can(verb, action) for r in roles)

    def request(self, action: str, key: str, params: dict | None = None, *, actor: Actor) -> Proposal:
        onto = self.studio.onto
        a = onto.actions.get(action)
        if a is None:
            raise KeyError(f"unknown action '{action}'")
        params = dict(params or {})
        checks = [CheckResult("role", self._allowed(actor, "request", action),
                              f"{actor.id} roles {actor.roles}")]
        missing = [p for p in a.parameters if p not in params]
        checks.append(CheckResult("parameters", not missing, f"missing {missing}" if missing else ""))
        obj = onto.obj(a.target)
        current = self.studio.fetch(a.target, key)
        checks.append(CheckResult("target", current is not None, f"{a.target} {key}"))
        changes: dict[str, Any] = {}
        for p, v in a.set.items():
            changes[p] = params.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v
        if a.transition_to and current is not None:
            sm = obj.states
            state = current.get(sm.property)
            ok = sm.allows(state, a.transition_to)
            checks.append(CheckResult("state", ok, f"{state} -> {a.transition_to}"))
            changes[sm.property] = a.transition_to
        for c in a.criteria:
            if c.decision and current is not None:
                res = self.studio.decide(c.decision, key)
                outs = res.outputs if isinstance(res.outputs, dict) else {}
                ok = all(outs.get(k) == v for k, v in c.expect.items())
                checks.append(CheckResult(f"decision:{c.decision}", ok, str(outs)))
            if c.states and current is not None:
                state = current.get(obj.states.property) if obj.states else None
                checks.append(CheckResult("states", state in c.states, f"{state} in {c.states}"))
        before = {p: current.get(p) for p in changes} if current else {}
        p = Proposal(f"P{next(self._ids)}", action, a.target, str(key), params, actor, "pending", checks, changes,
                     before)
        self.proposals[p.id] = p
        self._log(actor, "requested", p, params=params)
        if not all(c.passed for c in checks):
            p.status = "rejected"
            self._log(actor, "rejected", p, failed=[c.name for c in checks if not c.passed])
            return p
        auto = not a.approval and actor.kind == "human" and self._allowed(actor, "execute", action)
        if auto:
            self._execute(p, actor)
        return p

    def approve(self, proposal_id: str, *, approver: Actor) -> Proposal:
        p = self.proposals[proposal_id]
        if p.status != "pending":
            raise ValueError(f"proposal {p.id} is {p.status}")
        if approver.kind != "human":
            raise PermissionError("only a person approves an action")
        if not self._allowed(approver, "execute", p.action):
            raise PermissionError(f"{approver.id} may not execute {p.action}")
        p.approved_by = approver.id
        self._log(approver, "approved", p)
        self._execute(p, approver)
        return p

    def reject(self, proposal_id: str, *, approver: Actor, reason: str = "") -> Proposal:
        p = self.proposals[proposal_id]
        p.status = "rejected"
        self._log(approver, "rejected", p, reason=reason)
        return p

    def _execute(self, p: Proposal, actor: Actor) -> None:
        if self.writeback is None:
            raise RuntimeError("no write-back configured for actions")
        n = self.writeback.apply(self.studio.onto, p.target, p.key, p.changes)
        p.status = "executed"
        self._log(actor, "executed", p, before=p.before, after=p.changes, rows=n)

