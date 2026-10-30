"""Decision tables: inputs read from the ontology, rules as unary tests, outputs with the evidence behind them."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from xgen_data_studio.decide.cells import evaluate, parse_test
from xgen_data_studio.model import DecisionTable


class DecisionError(ValueError):
    """The decision cannot be evaluated as defined."""


@dataclass
class Evidence:
    input: str
    value: Any
    object_type: str = ""
    key: str = ""
    property: str = ""
    source: str = ""


@dataclass
class DecisionResult:
    decision: str
    outputs: Any
    matched: list[str]
    inputs: dict[str, Any]
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    engine: str = "native"
    target: str = ""
    key: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [asdict(e) for e in self.evidence]
        return d


def evaluate_table(table: DecisionTable, inputs: dict[str, Any]) -> tuple[Any, list[str], list[str]]:
    """Return (outputs, matched rule ids, rule notes) under the table's hit policy."""
    hits = []
    for rule in table.rules:
        if all(evaluate(parse_test(cell), inputs.get(name)) for name, cell in rule.when.items()):
            hits.append(rule)
            if table.hit_policy == "first":
                break
    if table.hit_policy == "unique" and len(hits) > 1:
        raise DecisionError(f"{table.name}: rules {[r.id for r in hits]} all match under hit policy 'unique'")
    ids, notes = [r.id for r in hits], [r.note for r in hits if r.note]
    if table.hit_policy == "collect":
        return [dict(r.then) for r in hits], ids, notes
    if not hits:
        return {k: None for k in table.outputs}, ids, notes
    return {k: hits[0].then.get(k) for k in table.outputs}, ids, notes
