import shutil
from datetime import datetime

import pytest

from xgen_data_studio.library import Library
from xgen_data_studio.modules import Module, ModuleError, Requirement, compose, removal_impact
from xgen_data_studio.studio import Studio

from .conftest import EXAMPLE

LIB = EXAMPLE.parent / "library"
ALL = ["core", "commerce", "commerce-bindings", "fashion", "acme-overlay", "finance", "finance-bindings"]
NOW = datetime(2026, 10, 30, 12, 0)


@pytest.fixture
def lib() -> Library:
    return Library(LIB)


@pytest.fixture
def composed(lib) -> Studio:
    from xgen_data_studio.backends.sql import SqliteBackend

    st = Studio.from_library(lib, ALL, now=lambda: NOW)
    src = SqliteBackend()
    src.script((EXAMPLE / "seed.sql").read_text(encoding="utf-8"))
    src.script((LIB / "seed_finance.sql").read_text(encoding="utf-8"))
    st.add_backend("source", src)
    return st


def test_library_lists_every_package(lib):
    rows = {r["name"]: r for r in lib.list()}
    assert set(rows) == {*ALL, "food"}
    assert rows["finance"]["kind"] == "domain" and rows["acme-overlay"]["kind"] == "customer"
    assert rows["commerce-bindings"]["requires"] == ["commerce"]


def test_composition_records_who_did_what(composed):
    c = composed.composition
    assert c.issues == []
    assert [m.name for m in c.modules][:2] == ["core", "commerce"]
    assert c.owner("object:Order") == "commerce" and c.owner("object:Loan") == "finance"
    assert c.owner("property:OrderItem.gift_wrap") == "acme-overlay"
    assert c.touched["decision:returnEligibility"] == ["acme-overlay"]
    assert "query:wishlistCount" in c.removed
    assert composed.onto.obj("Order").table == "orders" and composed.onto.obj("Party").abstract


def test_concept_queries_span_domains(composed):
    parties = composed.run("allParties").rows
    assert [p[0] for p in parties] == ["B01", "B02", "B03", "C001", "C002", "C003"]
    agreements = composed.run("agreementsSince", {"since": "2026-10-01T00:00:00"}).rows
    assert [a[0] for a in agreements] == ["L4", "O1", "O2", "O3", "O4"]
    assert "UNION ALL" in composed.translate("allParties", "sql:postgres").text


def test_composed_studio_conforms_and_answers(composed):
    pytest.importorskip("rdflib")
    from xgen_data_studio.backends.rdf import RdflibBackend

    composed.add_backend("graph", RdflibBackend())
    composed.project()
    assert composed.conformance().passed
    rep = composed.questions()
    assert rep.accuracy == 1.0, [(r.id, r.got, r.error) for r in rep.results if not r.passed]
    assert {r.id for r in rep.results} >= {"Q1", "F1", "A1", "L1", "L2"}


def test_customer_overlay_plugs_in_and_out(composed):
    vip = "VIP 고객은 배송 완료 후 14일까지 반품할 수 있습니다"
    assert composed.decide("returnEligibility", "I1001").outputs["reason"] == vip
    impact = composed.detach("acme-overlay")
    assert impact.ok and "property:OrderItem.gift_wrap" in impact.removed
    assert composed.decide("returnEligibility", "I1001").outputs["reason"] == "배송 완료 후 반품기간 7일 이내입니다"
    assert "wishlistCount" in composed.onto.queries
    composed.attach("acme-overlay")
    assert composed.decide("returnEligibility", "I1001").outputs["reason"] == vip


def test_detach_refuses_what_others_need(composed):
    imp = composed.detach_impact("commerce")
    assert not imp.ok and set(imp.dependents) == {"acme-overlay", "commerce-bindings", "fashion"}
    with pytest.raises(ModuleError):
        composed.detach("commerce")
    imp = composed.detach_impact("fashion")
    assert imp.ok and imp.removed == ["property:Sku.material", "property:Sku.season", "query:skusByMaterial",
                                      "question:F1"]
    composed.detach("commerce", cascade=True)
    assert "Order" not in composed.onto.objects and composed.run("allParties").rows[0][0] == "B01"


def test_attach_pulls_in_requirements(lib, composed):
    composed.detach("finance-bindings")
    composed.detach("finance")
    assert "Loan" not in composed.onto.objects
    composed.attach("finance-bindings")
    assert {"finance", "finance-bindings"} <= {m.name for m in composed.composition.modules}
    assert composed.run("overdueLoans").rows == [("최민준", "L2", 12000000.0)]


def test_definitions_without_bindings_do_not_run(lib):
    st = Studio.from_library(lib, ["finance"])
    from xgen_data_studio.compile.base import CompileError

    with pytest.raises(CompileError):
        st.translate("overdueLoans", "sql:sqlite")
    assert "MATCH (b:`Borrower`)-[:`borrows`]->(l:`Loan`)" in st.translate("overdueLoans", "cypher").text


def _mod(name, **kw):
    return Module.from_dict({"module": name, "namespace": "https://example.org/t#", **kw})


def test_conflicts_requirements_and_cycles():
    a = _mod("a", objects={"X": {"key": "id", "properties": {"id": "string"}}})
    clash = _mod("b", requires=["a"], objects={"X": {"key": "id", "properties": {"id": "integer"}}})
    with pytest.raises(ModuleError, match="already defined by a"):
        compose([a, clash])
    same = _mod("c", requires=["a"], objects={"X": {"key": "id", "properties": {"id": "string"}}})
    assert compose([a, same]).issues == []
    with pytest.raises(ModuleError, match="not attached"):
        compose([_mod("d", requires=["zzz"])])
    with pytest.raises(ModuleError, match="2.0"):
        compose([a, _mod("e", requires=["a>=2.0"])])
    with pytest.raises(ModuleError, match="cycle"):
        compose([_mod("p", requires=["q"]), _mod("q", requires=["p"])])
    with pytest.raises(ModuleError, match="changes the type"):
        compose([a, _mod("f", requires=["a"], extend={"objects": {"X": {"properties": {"id": {"type": "integer"}}}}})])
    assert Requirement.parse("core@1").allows("1.4.0") and not Requirement.parse("core>=1.10").allows("1.9.0")


def test_removal_impact_finds_broken_references():
    base = _mod("base", objects={"X": {"key": "id", "properties": {"id": "string", "n": "integer"}}})
    extra = _mod("extra", requires=["base"], extend={"objects": {"X": {"properties": {"m": "integer"}}}})
    use = _mod("use", requires=["base"],
               queries={"q": {"query": {"match": {"x": "X"}, "return": ["x.m"]}}})
    imp = removal_impact([base, extra, use], "extra")
    assert not imp.ok and any("no property 'm'" in b for b in imp.broken)


def test_library_versions_diff_delete(tmp_path):
    shutil.copytree(LIB, tmp_path / "lib")
    lib = Library(tmp_path / "lib")
    m = lib.get("fashion")
    m.version = "1.1.0"
    m.extend["objects"]["Sku"]["properties"]["fit"] = {"type": "enum", "values": ["SLIM", "REGULAR"]}
    lib.save(m)
    assert lib.versions("fashion") == ["1.0.0", "1.1.0"]
    assert lib.get("fashion").version == "1.1.0" and lib.get("fashion", "1.0.0").version == "1.0.0"
    assert lib.diff("fashion", "1.0.0", "1.1.0") == {"added": [], "removed": [], "changed": ["extend object:Sku"]}
    with pytest.raises(ModuleError):
        lib.save(m)
    with pytest.raises(ModuleError, match="requires commerce"):
        lib.delete("commerce")
    new = lib.create("energy", kind="domain", label="에너지 설비", requires=["core"])
    assert new.key == "energy@0.1.0" and "energy" in lib.names()
    lib.delete("energy")
    assert "energy" not in lib.names()
    assert [x.name for x in lib.resolve(["acme-overlay"])] == ["acme-overlay", "commerce", "commerce-bindings", "core"]


def test_import_standard_as_module(tmp_path, lib):
    pytest.importorskip("rdflib")
    from xgen_data_studio.exchange.owl import to_owl

    onto = Studio.from_library(lib, ["finance"]).onto
    ttl, _ = to_owl(onto)
    assert "skos:exactMatch <https://spec.edmcouncil.org/fibo/ontology/LOAN/LoansGeneral/Loans/Loan>" in ttl
    target = Library(tmp_path / "lib2")
    m, rep = target.import_owl(ttl, "fin-imported", requires=[])
    assert m.body["objects"]["Loan"]["aligned"] == [
        "https://spec.edmcouncil.org/fibo/ontology/LOAN/LoansGeneral/Loans/Loan"]
    assert target.get("fin-imported").kind == "domain" and rep.summary()["unsupported"] == 0


def test_bindings_check_against_the_database(composed):
    rep = composed.check_bindings()
    assert rep.ok and rep.checked["columns"] > 40 and rep.findings == []
    composed.backend("source").run("UPDATE orders SET status = 'LOST' WHERE order_id = 'O4'")
    composed.backend("source").run("INSERT INTO order_items (item_id, order_id, sku_id) VALUES ('I9', 'O1', 'S9')")
    kinds = {(f.kind, f.element) for f in composed.check_bindings().findings}
    assert ("enum", "property:Order.status") in kinds and ("orphan", "link:ofSku") in kinds
    composed.attach("food")
    rep = composed.check_bindings()
    assert not rep.ok
    assert {f.element for f in rep.findings if f.kind == "column"} == {"property:Sku.expires_on", "property:Sku.storage"}


def test_library_screen(composed):
    from xgen_data_studio.preview import render

    html = render(composed, query="revenueByCategory", decision="returnEligibility", key="I1001")
    assert 'id="library"' in html and "식품 업종 확장" in html and "빼기 전 영향" in html
    assert "상위 개념" in html and "하위 유형" in html
