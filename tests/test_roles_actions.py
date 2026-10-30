import pytest

from xgen_data_studio.actions import Actor
from xgen_data_studio.roles import AccessDenied

ME = {"customer_id": "C001"}
AGENT = Actor("agent-1", "agent", ["customer_agent"])
OPERATOR = Actor("op", "human", ["operator"])


def test_row_filters(studio):
    rows = studio.run("myOrders", role="customer_agent", principal=ME).rows
    assert {r[0] for r in rows} == {"O1", "O2"}
    rows = studio.run({"match": {"i": "OrderItem"}, "return": ["i.item_id"], "order": ["item_id"]},
                      role="customer_agent", principal=ME).rows
    assert rows == [("I1001",), ("I1002",), ("I1005",)]
    rows = studio.run({"match": {"s": "Sku"}, "where": {"exists": {"match": {"i": "OrderItem"},
                                                                    "edges": [["i", "ofSku", "s"]]}},
                       "return": ["s.sku_id"], "order": ["sku_id"]}, role="customer_agent", principal=ME).rows
    assert rows == [("S1",), ("S2",), ("S3",)]


def test_role_denials(studio):
    with pytest.raises(AccessDenied, match="may not read Customer"):
        studio.run({"match": {"c": "Customer"}, "return": ["c.name"]}, role="customer_agent", principal=ME)
    with pytest.raises(AccessDenied, match="principal"):
        studio.run("myOrders", role="customer_agent")
    with pytest.raises(AccessDenied, match="may not run"):
        studio.run("revenueByCategory", role="customer_agent", principal=ME)


def test_action_needs_a_person(studio):
    p = studio.actions.request("requestReturn", "I1001", {"reason": "사이즈"}, actor=AGENT)
    assert p.status == "pending" and all(c.passed for c in p.checks)
    with pytest.raises(PermissionError):
        studio.actions.approve(p.id, approver=Actor("bot", "agent", ["operator"]))
    studio.actions.approve(p.id, approver=OPERATOR)
    assert p.status == "executed" and p.before == {"item_status": "NORMAL"}
    assert studio.fetch("OrderItem", "I1001")["item_status"] == "RETURN_REQUESTED"
    assert [e.event for e in studio.actions.audit] == ["requested", "approved", "executed"]
    assert studio.actions.audit[-1].detail["after"] == {"item_status": "RETURN_REQUESTED"}


def test_action_rejected_by_decision_or_state(studio):
    p = studio.actions.request("requestReturn", "I1003", {"reason": "변심"}, actor=AGENT)
    assert p.status == "rejected"
    failed = {c.name for c in p.checks if not c.passed}
    assert failed == {"decision:returnEligibility"}
    p = studio.actions.request("requestReturn", "I1002", {"reason": "x"}, actor=AGENT)
    assert {c.name for c in p.checks if not c.passed} == {"state", "decision:returnEligibility"}
    p = studio.actions.request("requestReturn", "I1001", {}, actor=Actor("x", "agent", []))
    assert {c.name for c in p.checks if not c.passed} == {"role", "parameters"}
