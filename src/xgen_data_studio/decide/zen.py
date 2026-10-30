"""Decision-table export to GoRules JDM, and evaluation on the ZEN engine when it is installed."""
from __future__ import annotations

import json
from typing import Any

from xgen_data_studio.decide.cells import parse_test, to_zen
from xgen_data_studio.decide.table import DecisionError
from xgen_data_studio.model import DecisionTable


def to_jdm(table: DecisionTable) -> dict:
    if table.hit_policy not in ("first", "collect"):
        raise DecisionError(f"ZEN decision tables take hit policy first or collect, not '{table.hit_policy}'")
    inputs = [{"id": f"in_{n}", "name": n, "field": n} for n in table.inputs]
    outputs = [{"id": f"out_{n}", "name": n, "field": n} for n in table.outputs]
    rules = []
    for r in table.rules:
        row: dict[str, str] = {"_id": r.id, "_description": r.note}
        for n in table.inputs:
            row[f"in_{n}"] = to_zen(parse_test(r.when.get(n, "")))
        for n in table.outputs:
            row[f"out_{n}"] = json.dumps(r.then[n], ensure_ascii=False) if n in r.then else ""
        rules.append(row)
    return {
        "contentType": "application/vnd.gorules.decision",
        "nodes": [
            {"id": "request", "name": "request", "type": "inputNode", "position": {"x": 0, "y": 0}},
            {"id": "table", "name": table.name, "type": "decisionTableNode", "position": {"x": 320, "y": 0},
             "content": {"hitPolicy": table.hit_policy, "inputs": inputs, "outputs": outputs, "rules": rules}},
            {"id": "response", "name": "response", "type": "outputNode", "position": {"x": 640, "y": 0}},
        ],
        "edges": [{"id": "e1", "sourceId": "request", "targetId": "table", "type": "edge"},
                  {"id": "e2", "sourceId": "table", "targetId": "response", "type": "edge"}],
    }


def evaluate_zen(table: DecisionTable, inputs: dict[str, Any]) -> Any:
    try:
        import zen
    except ImportError as e:
        raise ImportError("ZEN evaluation needs the [zen] extra (zen-engine)") from e
    engine = zen.ZenEngine()
    decision = engine.create_decision(json.dumps(to_jdm(table), ensure_ascii=False))
    out = decision.evaluate(dict(inputs))
    result = out.get("result", out)
    if table.hit_policy == "collect":
        return [{k: r.get(k) for k in table.outputs} for r in (result or [])]
    if not result:
        return {k: None for k in table.outputs}
    return {k: result.get(k) for k in table.outputs}
