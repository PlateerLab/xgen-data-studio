"""Conformance: run the same IR on several backends and check they give the same answer."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from xgen_data_studio.ir import Query
from xgen_data_studio.values import normalize


@dataclass
class Outcome:
    backend: str
    rows: list[tuple] | None = None
    error: str = ""
    text: str = ""


@dataclass
class QueryReport:
    name: str
    outcomes: dict[str, Outcome]
    agree: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "agree": self.agree, "detail": self.detail,
                "outcomes": {b: {"rows": o.rows, "error": o.error} for b, o in self.outcomes.items()}}


@dataclass
class ConformanceReport:
    queries: list[QueryReport] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(q.agree for q in self.queries)

    def summary(self) -> dict[str, Any]:
        return {"queries": len(self.queries), "agree": sum(q.agree for q in self.queries),
                "disagree": [q.name for q in self.queries if not q.agree]}

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "queries": [q.to_dict() for q in self.queries]}


def normalize_rows(rows: list[tuple], columns: list[str], types: dict[str, str]) -> list[tuple]:
    return [tuple(normalize(v, types.get(c, "")) for v, c in zip(r, columns)) for r in rows]


def _same(q: Query, a: list[tuple], b: list[tuple], columns: list[str]) -> tuple[bool, str]:
    if Counter(a) != Counter(b):
        return False, f"rows differ: {sorted(set(a) ^ set(b), key=repr)[:5]}"
    if q.order:
        idx = [columns.index(o.name) for o in q.order]
        ka, kb = [tuple(r[i] for i in idx) for r in a], [tuple(r[i] for i in idx) for r in b]
        if ka != kb:
            return False, "same rows, different order on the order keys"
    return True, ""


def run(onto, backends: dict[str, Any], queries: dict[str, tuple[Query, dict]]) -> ConformanceReport:
    report = ConformanceReport()
    for name, (q, params) in queries.items():
        outcomes: dict[str, Outcome] = {}
        for bname, b in backends.items():
            missing = b.unsupported(q)
            if missing:
                outcomes[bname] = Outcome(bname, error="unsupported: " + ", ".join(missing))
                continue
            try:
                compiled = b.compiler(onto).compile(q)
                res = b.execute(compiled, params)
                outcomes[bname] = Outcome(bname, normalize_rows(res.rows, res.columns, compiled.column_types),
                                          text=compiled.text)
            except Exception as e:
                outcomes[bname] = Outcome(bname, error=f"{type(e).__name__}: {e}")
        ran = [o for o in outcomes.values() if o.rows is not None]
        agree, detail = True, ""
        failed = [o for o in outcomes.values() if o.error and not o.error.startswith("unsupported")]
        if failed:
            agree, detail = False, "; ".join(f"{o.backend}: {o.error}" for o in failed)
        elif len(ran) >= 2:
            first = ran[0]
            for o in ran[1:]:
                ok, why = _same(q, first.rows, o.rows, [c.name for c in q.columns])
                if not ok:
                    agree, detail = False, f"{first.backend} vs {o.backend}: {why}"
                    break
        report.queries.append(QueryReport(name, outcomes, agree, detail))
    return report
