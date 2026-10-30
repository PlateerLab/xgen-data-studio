import pytest

from xgen_data_studio.decide.cells import CellError, IsNull, Range, evaluate, parse_test, to_zen
from xgen_data_studio.decide.table import DecisionError, evaluate_table
from xgen_data_studio.model import DecisionRule, DecisionTable


@pytest.mark.parametrize("cell, value, hit", [
    ("", None, True), ("-", 3, True), ("null", None, True), ("null", 0, False), ("not null", 0, True),
    ("<= 7", 7, True), ("<= 7", 8, False), ("<= 7", None, False), ("[1..7]", 1, True), ("(1..7]", 1, False),
    ('"VIP"', "VIP", True), ("'VIP'", "BASIC", False), ('!= "NORMAL"', "RETURNED", True),
    ('in ["A", "B"]', "B", True), ('not in ["A", "B"]', "B", False), ('"A", "B"', "A", True),
    ("true", True, True), ("false", True, False), ("3", 3.0, True),
])
def test_cells(cell, value, hit):
    assert evaluate(parse_test(cell), value) is hit


def test_cell_errors_and_zen_text():
    with pytest.raises(CellError):
        parse_test("<= seven")
    assert to_zen(parse_test("[1..7]")) == "$ >= 1 and $ <= 7"
    assert to_zen(parse_test("null")) == "$ == null"
    assert isinstance(parse_test("not null"), IsNull) and isinstance(parse_test("[1..2)"), Range)


def _table(policy):
    return DecisionTable("t", {}, {"x": "integer"}, [DecisionRule({"a": "> 1"}, {"x": 1}, "r1"),
                                                     DecisionRule({"a": "> 2"}, {"x": 2}, "r2")], hit_policy=policy)


def test_hit_policies():
    assert evaluate_table(_table("first"), {"a": 3})[:2] == ({"x": 1}, ["r1"])
    assert evaluate_table(_table("collect"), {"a": 3})[0] == [{"x": 1}, {"x": 2}]
    with pytest.raises(DecisionError):
        evaluate_table(_table("unique"), {"a": 3})
    assert evaluate_table(_table("first"), {"a": 0})[0] == {"x": None}


def test_decision_with_evidence(studio):
    r = studio.decide("returnEligibility", "I1001")
    assert r.outputs == {"eligible": True, "reason": "배송 완료 후 반품기간 7일 이내입니다"}
    assert r.matched == ["in-window"]
    sources = {e.input: e.source for e in r.evidence}
    assert sources == {"days_since_delivery": "order_items.delivered_at", "item_status": "order_items.item_status",
                       "category_returnable": "categories.returnable"}
    assert {k: studio.decide("returnEligibility", k).matched[0] for k in ("I1002", "I1003", "I1004", "I1005")} == {
        "I1002": "in-progress", "I1003": "expired", "I1004": "category", "I1005": "not-delivered"}


def test_zen_agrees_with_native(studio):
    pytest.importorskip("zen")
    from xgen_data_studio.decide.zen import evaluate_zen, to_jdm

    table = studio.onto.decisions["returnEligibility"]
    assert to_jdm(table)["nodes"][1]["content"]["hitPolicy"] == "first"
    for key in ("I1001", "I1002", "I1003", "I1004", "I1005"):
        native = studio.decide("returnEligibility", key)
        assert evaluate_zen(table, native.inputs) == native.outputs, key


def test_validation_questions(studio):
    rep = studio.questions()
    assert rep.accuracy == 1.0, [(r.id, r.got, r.error) for r in rep.results if not r.passed]
