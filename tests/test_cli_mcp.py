import asyncio
import json

import pytest

from xgen_data_studio.cli import main
from xgen_data_studio.tools import StudioTools

from .conftest import EXAMPLE


def _run(capsys, *args) -> tuple[int, str]:
    code = main([str(a) for a in args])
    return code, capsys.readouterr().out


def test_cli_validate_translate_export(capsys):
    pytest.importorskip("yaml")
    code, out = _run(capsys, "validate", EXAMPLE / "ontology.yaml")
    assert code == 0 and json.loads(out)["ok"]
    code, out = _run(capsys, "translate", EXAMPLE / "ontology.yaml", "lowStock", "--to", "cypher",
                     "--param", "threshold=5")
    data = json.loads(out)
    assert data["language"] == "cypher" and "s.`stock` < 5" in data["preview"]
    code, out = _run(capsys, "translate", EXAMPLE / "ontology.yaml",
                     "MATCH (o:Order) RETURN o.status, count(o) AS n", "--from", "cypher", "--to", "sql:sqlite")
    assert "GROUP BY" in json.loads(out)["text"]
    code, out = _run(capsys, "export", EXAMPLE / "ontology.yaml", "--format", "pgq")
    assert out.startswith("CREATE PROPERTY GRAPH")


def test_cli_studio_commands(capsys):
    pytest.importorskip("yaml")
    pytest.importorskip("rdflib")
    cfg = EXAMPLE / "studio.yaml"
    code, out = _run(capsys, "questions", cfg)
    assert code == 0 and json.loads(out)["accuracy"] == 1.0
    code, out = _run(capsys, "conformance", cfg)
    assert code == 0 and json.loads(out)["summary"]["disagree"] == []
    code, out = _run(capsys, "decide", cfg, "returnEligibility", "I1004")
    assert json.loads(out)["outputs"]["reason"] == "반품할 수 없는 카테고리입니다"
    code, out = _run(capsys, "cypher", cfg, "MATCH (p:Product) WHERE p.name CONTAINS '니트' RETURN p.name",
                     "--backend", "graph")
    assert json.loads(out)["rows"] == [{"name": "울 니트 스웨터"}]


def test_tools_are_role_scoped(studio):
    t = StudioTools(studio, role="customer_agent", principal={"customer_id": "C001"})
    assert "Customer" not in t.describe()["objects"]
    assert t.decide("returnEligibility", "I1001")["outputs"]["eligible"] is True
    with pytest.raises(PermissionError):
        t.decide("returnEligibility", "I1003")
    p = t.request_action("requestReturn", "I1001", {"reason": "사이즈"})
    assert p["status"] == "pending" and p["requested_by"]["kind"] == "agent"
    assert [r["item_id"] for r in t.run_query("myOrders")["rows"]] == ["I1001", "I1002", "I1005"]
    with pytest.raises(PermissionError):
        StudioTools(studio, read_only=True).request_action("requestReturn", "I1001", {})


def test_mcp_server_lists_and_calls_tools(studio):
    pytest.importorskip("mcp")
    from xgen_data_studio.mcp_server import build_server

    srv = build_server(studio, role="customer_agent", principal={"customer_id": "C001"}, read_only=True)
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"describe_ontology", "run_query", "run_sparql", "run_cypher", "decide", "translate_query"} <= names
    assert "request_action" not in names
    res = asyncio.run(srv.call_tool("translate_query", {"query": "lowStock", "to": "sql:mysql"}))
    assert "`skus`" in str(res)
