import json

from xgen_data_studio.catalog import from_ontology
from xgen_data_studio.nl import IRGenerator, answer, extract_json, schema_card


def _catalog(onto):
    c = from_ontology(onto)
    c.add_folder("정책서")
    c.add_file("정책서/반품정책.pdf", folder="정책서", collection="커머스-정책")
    c.add_file("정책서/옛-공지.pdf", folder="정책서")
    c.add_agent("고객응대", roles=["customer_agent"], uses=["collection:커머스-정책"])
    return c


def test_impact_of_a_column(onto):
    ids = [a.id for a in _catalog(onto).impact("column:order_items.delivered_at")]
    assert ids == ["action:requestReturn", "agent:고객응대", "decision:returnEligibility",
                   "property:OrderItem.delivered_at", "query:deliveredWithoutClaim", "role:customer_agent"]


def test_what_an_agent_sees(onto):
    seen = {a.id for a in _catalog(onto).sees("고객응대")}
    assert {"table:order_items", "column:order_items.delivered_at", "file:정책서/반품정책.pdf"} <= seen
    assert "table:customers" not in seen and "file:정책서/옛-공지.pdf" not in seen


def test_unused_assets(onto):
    unused = {a.id for a in _catalog(onto).unused()}
    assert {"table:customers", "file:정책서/옛-공지.pdf", "table:wishlists"} <= unused
    assert "table:order_items" not in unused


def test_schema_card_respects_role(onto):
    card = schema_card(onto, "customer_agent")
    assert "OrderItem (주문상품)" in card and "Customer (" not in card and "myOrders" in card


def test_extract_json():
    assert extract_json('here:\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}
    assert extract_json("no json") is None


def test_generator_repairs_with_issues(studio):
    replies = iter([
        "not json at all",
        json.dumps({"match": {"s": "Sku"}, "where": {"lt": ["s.stok", 5]}, "return": ["s.sku_id"]}),
        json.dumps({"match": {"s": "Sku"}, "where": {"lt": ["s.stock", 5]}, "return": ["s.sku_id"],
                    "order": ["sku_id"]}),
    ])
    prompts = []

    def llm(system, prompt):
        prompts.append(prompt)
        return next(replies)

    gen = IRGenerator(studio.onto, llm, max_repairs=2).generate("재고 5개 미만 단품")
    assert gen.ok and len(gen.attempts) == 3
    assert "has no property 'stok'" in prompts[2]
    assert studio.run(gen.query).rows == [("S1",), ("S3",)]


def test_answer_with_a_registered_query(studio):
    out = answer(studio, "내 주문", lambda s, p: '{"query": "myOrders"}', role="customer_agent",
                 principal={"customer_id": "C002"})
    assert out["ok"] and {r[0] for r in out["rows"]} == {"O3", "O4"}
