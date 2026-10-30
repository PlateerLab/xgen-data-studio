import pytest

from xgen_data_studio.check import CheckError, check, check_or_raise
from xgen_data_studio.ir import IRError, Query


def _issues(onto, d):
    return check(Query.from_dict(d), onto).issues


def test_ir_round_trip(onto):
    for rq in onto.queries.values():
        q = Query.from_dict(rq.query)
        assert Query.from_dict(q.to_dict()).to_dict() == q.to_dict()


def test_default_column_names():
    q = Query.from_dict({"match": {"a": "Order", "b": "Customer"}, "edges": [["b", "placed", "a"]],
                         "return": ["a.status", "a.order_id", {"count": "b"}, "b.customer_id"]})
    assert [c.name for c in q.columns] == ["status", "order_id", "count_b", "customer_id"]
    q = Query.from_dict({"match": {"a": "Order", "o": "Order"}, "return": ["a.order_id", "o.order_id"]})
    assert [c.name for c in q.columns] == ["a_order_id", "o_order_id"]


def test_inverse_link_resolves_direction(onto):
    q = check_or_raise({"match": {"i": "OrderItem", "o": "Order"}, "edges": [["i", "itemOf", "o"]],
                        "return": ["i.item_id"]}, onto).query
    assert q.edges[0].link == "hasItem" and q.edges[0].reverse is True
    q = check_or_raise({"match": {"o": "Order", "i": "OrderItem"}, "edges": [["o", "hasItem", "i"]],
                        "return": ["i.item_id"]}, onto).query
    assert q.edges[0].reverse is False


@pytest.mark.parametrize("d, needle", [
    ({"match": {"o": "Nope"}, "return": ["o.x"]}, "unknown object type"),
    ({"match": {"o": "Order"}, "return": ["o.price"]}, "has no property 'price'"),
    ({"match": {"o": "Order"}, "where": {"eq": ["o.status", "LOST"]}, "return": ["o.order_id"]}, "one of"),
    ({"match": {"o": "Order", "c": "Customer"}, "return": ["o.order_id"]}, "not connected"),
    ({"match": {"o": "Order", "s": "Sku"}, "edges": [["o", "ofSku", "s"]], "return": ["o.order_id"]},
     "cannot join"),
    ({"match": {"k": "Product", "a": "Product"}, "edges": [{"from": "k", "link": "skuOf", "to": "a", "hops": 3}],
      "return": ["a.name"]}, "link from a type to itself"),
    ({"match": {"s": "Sku"}, "return": [{"sum": "s.size", "as": "x"}]}, "needs a number"),
    ({"match": {"s": "Sku"}, "return": ["s.sku_id"], "order": ["price"]}, "not a returned column"),
    ({"match": {"c": "Customer", "o": "Order", "i": "OrderItem"},
      "edges": [{"from": "c", "link": "placed", "to": "o", "optional": True}, ["o", "hasItem", "i"]],
      "return": ["c.name"]}, "optional alias"),
])
def test_check_issues(onto, d, needle):
    issues = _issues(onto, d)
    assert any(needle in i for i in issues), issues


def test_param_types_are_inferred(onto):
    res = check(Query.from_dict(onto.queries["lowStock"].query), onto)
    assert res.param_types == {"threshold": "integer"}
    assert res.column_types == {"sku_id": "string", "stock": "integer"}


def test_malformed_ir():
    with pytest.raises(IRError):
        Query.from_dict({"match": {"o": "Order"}, "return": []})
    with pytest.raises(IRError):
        Query.from_dict({"match": {"o": "Order"}, "where": {"eq": ["o.status"]}, "return": ["o.status"]})


def test_check_error_carries_issues(onto):
    with pytest.raises(CheckError) as e:
        check_or_raise({"match": {"o": "Order"}, "return": ["o.nope"]}, onto)
    assert e.value.issues
