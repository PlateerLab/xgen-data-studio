"""LLM assist: a question becomes IR (or a registered query), checked against the ontology and repaired."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from xgen_data_studio.check import check
from xgen_data_studio.ir import IRError, Query
from xgen_data_studio.model import Ontology

SYSTEM = ("You translate a question about business data into one JSON object in the ontology query IR. "
          "Use only the object types, properties and links listed. Answer with the JSON object only.")

IR_GUIDE = """IR format:
{"match": {"<alias>": "<ObjectType>", ...},
 "edges": [["<alias>", "<link or inverse>", "<alias>"], {"from": "a", "link": "l", "to": "b", "optional": true}],
 "where": {"and": [{"eq": ["a.prop", value]}, {"gte": ["b.prop", {"param": "name"}]},
                   {"in": ["a.prop", [v1, v2]]}, {"contains": ["a.prop", "text"]}, {"is_null": "a.prop"},
                   {"not_exists": {"match": {"c": "Type"}, "edges": [["a", "link", "c"]]}}]},
 "return": ["a.prop", {"col": "b.prop", "as": "name"}, {"count": "b", "as": "n"}, {"sum": "b.prop", "as": "total"}],
 "order": ["-total", "name"], "limit": 10}
Comparisons: eq ne lt lte gt gte. Aggregates: count count_distinct sum avg min max.
Every edge must start from an alias already matched. Dates are ISO text ("2026-10-01T00:00:00").
If a registered query answers the question, answer {"query": "<name>", "params": {...}} instead."""


def schema_card(onto: Ontology, role: str | None = None) -> str:
    r = onto.roles.get(role) if role else None
    lines = ["Object types:"]
    for o in onto.objects.values():
        if r and not r.can_read(o.name):
            continue
        props = []
        for p in o.properties.values():
            s = f"{p.name} {p.type}"
            if p.values:
                s += "[" + "|".join(p.values) + "]"
            if p.label:
                s += f" ({p.label})"
            if p.name == o.key:
                s += " key"
            props.append(s)
        lines.append(f"- {o.name}" + (f" ({o.label})" if o.label else "") + ": " + ", ".join(props))
    lines.append("Links:")
    for lk in onto.links.values():
        if r and not (r.can_read(lk.source) and r.can_read(lk.target)):
            continue
        s = f"- {lk.name}: {lk.source} -> {lk.target}"
        if lk.inverse:
            s += f" (inverse: {lk.inverse})"
        if lk.label:
            s += f" [{lk.label}]"
        lines.append(s)
    if onto.queries:
        lines.append("Registered queries:")
        for q in onto.queries.values():
            if r and not r.can("run", q.name):
                continue
            params = ", ".join(f"{k}: {v}" for k, v in q.params.items())
            lines.append(f"- {q.name}({params})" + (f": {q.label}" if q.label else ""))
    return "\n".join(lines)


def extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        return None
    depth, quote, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            esc = ch == "\\" and not esc
            if ch == '"' and not esc:
                quote = False
            continue
        if ch == '"':
            quote = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


@dataclass
class Attempt:
    prompt: str
    raw: str
    issues: list[str]


@dataclass
class Generated:
    query: Query | None = None
    registered: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.query is not None or bool(self.registered)


class IRGenerator:
    def __init__(self, onto: Ontology, llm: Callable[[str, str], str], *, role: str | None = None,
                 max_repairs: int = 2):
        self.onto, self.llm, self.role, self.max_repairs = onto, llm, role, max_repairs

    def _issues(self, data: Any) -> tuple[list[str], Query | None, str, dict]:
        if not isinstance(data, dict):
            return ["the answer was not one JSON object"], None, "", {}
        if isinstance(data.get("query"), str):
            name, params = data["query"], dict(data.get("params") or {})
            rq = self.onto.queries.get(name)
            if rq is None:
                return [f"unknown registered query '{name}'"], None, "", {}
            missing = [p for p in rq.params if p not in params]
            return ([f"missing parameters {missing} for {name}"] if missing else []), None, name, params
        try:
            q = Query.from_dict(data)
        except IRError as e:
            return [str(e)], None, "", {}
        res = check(q, self.onto)
        if self.role:
            r = self.onto.roles[self.role]
            res.issues += [f"this role cannot read {t}" for t in q.nodes.values() if not r.can_read(t)]
        return res.issues, q, "", dict(data.get("params") or {})

    def generate(self, question: str) -> Generated:
        base = f"{schema_card(self.onto, self.role)}\n\n{IR_GUIDE}\n\nQuestion: {question}"
        prompt, out = base, Generated()
        for _ in range(self.max_repairs + 1):
            raw = self.llm(SYSTEM, prompt)
            issues, q, name, params = self._issues(extract_json(raw))
            out.attempts.append(Attempt(prompt, raw, issues))
            if not issues:
                out.query, out.registered, out.params = q, name, params
                return out
            prompt = (base + "\n\nYour last answer:\n" + raw + "\n\nIt has these problems:\n"
                      + "\n".join(f"- {i}" for i in issues) + "\nReturn a corrected JSON object.")
        return out


def answer(studio, question: str, llm: Callable[[str, str], str], *, backend: str | None = None,
           role: str | None = None, principal: dict | None = None) -> dict:
    gen = IRGenerator(studio.onto, llm, role=role).generate(question)
    if not gen.ok:
        return {"ok": False, "issues": gen.attempts[-1].issues if gen.attempts else [], "attempts": len(gen.attempts)}
    target = gen.registered or gen.query
    res = studio.run(target, gen.params, backend=backend, role=role, principal=principal)
    return {"ok": True, "attempts": len(gen.attempts), "query": gen.registered or gen.query.to_dict(),
            "columns": res.columns, "rows": [list(r) for r in res.rows], "text": res.compiled.text}
