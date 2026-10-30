"""Role scoping: refuse unreadable types and AND each alias's row filter into the query."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from xgen_data_studio.ir import And, Exists, Not, Or, Query, parse_filter
from xgen_data_studio.model import Ontology, Role


class AccessDenied(PermissionError):
    """The role may not read or run this."""


def _rewrite(node: Any, alias: str, renames: dict[str, str], principal_attrs: set[str]) -> Any:
    if isinstance(node, dict):
        if set(node) == {"principal"}:
            principal_attrs.add(node["principal"])
            return {"param": f"principal__{node['principal']}"}
        out = {}
        for k, v in node.items():
            if k in ("exists", "not_exists") and isinstance(v, dict):
                inner = {**renames, **{a: f"{alias}__{a}" for a in v.get("match", {})}}
                v = {**v, "match": {inner[a]: t for a, t in v.get("match", {}).items()}}
                out[k] = _rewrite(v, alias, inner, principal_attrs)
            else:
                out[k] = _rewrite(v, alias, renames, principal_attrs)
        return out
    if isinstance(node, list):
        return [_rewrite(x, alias, renames, principal_attrs) for x in node]
    if isinstance(node, str):
        if node == "$self":
            return alias
        if "." in node and node.count(".") == 1:
            a, p = node.split(".")
            if a == "$self":
                return f"{alias}.{p}"
            if a in renames:
                return f"{renames[a]}.{p}"
        return renames.get(node, node)
    return node


def row_filter(role: Role, type_name: str, alias: str) -> tuple[Any, set[str]]:
    spec = role.row_filters.get(type_name)
    if not spec:
        return None, set()
    attrs: set[str] = set()
    return parse_filter(_rewrite(spec, alias, {}, attrs)), attrs


def _scope_filter(f: Any, role: Role, attrs: set[str], check) -> Any:
    if isinstance(f, (And, Or)):
        return type(f)([_scope_filter(x, role, attrs, check) for x in f.items])
    if isinstance(f, Not):
        return Not(_scope_filter(f.item, role, attrs, check))
    if isinstance(f, Exists):
        extra = []
        for a, t in f.nodes.items():
            check(t)
            rf, used = row_filter(role, t, a)
            attrs |= used
            if rf is not None:
                extra.append(rf)
        where = _scope_filter(f.where, role, attrs, check)
        parts = ([where] if where is not None else []) + extra
        return replace(f, where=And(parts) if len(parts) > 1 else (parts[0] if parts else None))
    return f


def apply_role(onto: Ontology, q: Query, role_name: str, principal: dict | None) -> tuple[Query, dict]:
    role = onto.roles.get(role_name)
    if role is None:
        raise AccessDenied(f"unknown role '{role_name}'")

    def check(t: str) -> None:
        if not role.can_read(t):
            raise AccessDenied(f"role {role.name} may not read {t}")

    attrs: set[str] = set()
    filters = []
    for a, t in q.nodes.items():
        check(t)
        rf, used = row_filter(role, t, a)
        attrs |= used
        if rf is not None:
            filters.append(rf)
    q = replace(q, where=_scope_filter(q.where, role, attrs, check))
    if filters:
        q = q.with_where(filters[0] if len(filters) == 1 else And(filters))
    principal = principal or {}
    missing = sorted(a for a in attrs if a not in principal)
    if missing:
        raise AccessDenied(f"role {role.name} needs principal attributes {missing}")
    return q, {f"principal__{a}": principal[a] for a in attrs}
