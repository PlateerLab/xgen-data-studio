import pytest

from xgen_data_studio.projection import Projection, project
from xgen_data_studio.rdf import Iris
from xgen_data_studio.reason.rules import run_rules, with_derived


def test_rules_derive_inverse_and_transitive(onto, source):
    res = run_rules(onto, project(onto, source))
    trans = [(d.source_key, d.target_key) for d in res.derived if d.rule == "transitive:broader"]
    assert trans == [("K3", "K1")]
    d = next(d for d in res.derived if d.rule == "transitive:broader")
    assert d.because == [("broader", "Category", "K3", "Category", "K2"), ("broader", "Category", "K2", "Category", "K1")]
    assert ("narrower", "Category", "K1", "Category", "K3") in res.edges()
    assert res.findings == []


def test_rule_findings(onto, source):
    proj = project(onto, source)
    proj.nodes[("Order", "O9")] = {"order_id": "O9", "status": "LOST"}
    proj.edges.add(("ofSku", "OrderItem", "I1001", "Sku", "S2"))
    kinds = {(f.kind, f.key) for f in run_rules(onto, proj).findings}
    assert ("missing_link", "O9") in kinds and ("enum", "O9") in kinds and ("state", "O9") in kinds
    assert ("cardinality", "I1001") in kinds


def test_shacl(onto, source):
    pytest.importorskip("pyshacl")
    from xgen_data_studio.reason.shacl import to_shacl, validate

    assert "sh:in (\"ORDERED\"" in to_shacl(onto)
    proj = project(onto, source)
    assert validate(onto, proj).conforms
    bad = Projection(dict(proj.nodes), set(proj.edges))
    bad.nodes[("Sku", "S1")] = {**bad.nodes[("Sku", "S1")], "sku_id": None}
    bad.edges.add(("ofSku", "OrderItem", "I1001", "Sku", "S2"))
    rep = validate(onto, bad)
    assert not rep.conforms
    assert {r["constraint"] for r in rep.results} >= {"MinCountConstraintComponent", "MaxCountConstraintComponent"}


def test_owl_rl_agrees_with_native_rules(onto, source):
    pytest.importorskip("owlrl")
    from xgen_data_studio.reason.owl_rl import materialize

    proj = project(onto, source)
    ir = Iris(onto)
    native = {(ir.node(d.source_type, d.source_key), ir.link(d.link), ir.node(d.target_type, d.target_key))
              for d in run_rules(onto, proj).derived}
    rl = {t for t in materialize(onto, proj) if t[1] != "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"}
    assert rl == native


def test_derived_edges_are_queryable(graph_studio):
    from xgen_data_studio.projection import load

    onto = graph_studio.onto
    proj = with_derived(graph_studio.projection, run_rules(onto, graph_studio.projection))
    load(onto, proj, graph_studio.backend("graph"))
    q = {"match": {"k": "Category", "a": "Category"}, "edges": [["k", "broader", "a"]],
         "where": {"eq": ["k.category_id", "K3"]}, "return": [{"col": "a.name", "as": "n"}], "order": ["n"]}
    assert graph_studio.run(q, backend="graph").rows == [("상의",), ("의류",)]
