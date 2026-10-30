import pytest

from xgen_data_studio.exchange.owl import to_owl
from xgen_data_studio.exchange.r2rml import to_r2rml


def test_owl_export_parses_and_reports(onto):
    rdflib = pytest.importorskip("rdflib")
    ttl, rep = to_owl(onto)
    g = rdflib.Graph().parse(data=ttl, format="turtle")
    owl = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
    ns = rdflib.Namespace(onto.namespace)
    assert (ns.Order, rdflib.RDF.type, owl.Class) in g
    assert (ns.broader, rdflib.RDF.type, owl.TransitiveProperty) in g
    assert (ns.broader, rdflib.RDF.type, owl.FunctionalProperty) not in g
    assert (ns.itemOf, owl.inverseOf, ns.hasItem) in g
    assert any("decision table returnEligibility" in u for u in rep.unsupported)
    assert any("transitive" in a for a in rep.adjusted)


def test_r2rml_matches_the_projection_iris(onto):
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph().parse(data=to_r2rml(onto), format="turtle")
    rr = rdflib.Namespace("http://www.w3.org/ns/r2rml#")
    templates = {str(o) for o in g.objects(None, rr.template)}
    assert "https://example.org/commerce#Order/{order_id}" in templates
    assert "https://example.org/commerce#Product/{product_id}" in templates
    joins = {(str(g.value(j, rr.child)), str(g.value(j, rr.parent))) for j in g.objects(None, rr.joinCondition)}
    assert ("order_id", "order_id") in joins and ("parent_id", "category_id") in joins


def test_owl_import_round_trip(onto):
    pytest.importorskip("rdflib")
    from xgen_data_studio.exchange.importer import from_owl

    back, rep = from_owl(to_owl(onto)[0])
    assert set(onto.objects) <= set(back.objects)
    assert set(back.links) == set(onto.links)
    assert back.links["broader"].transitive and back.links["broader"].inverse == "narrower"
    assert back.links["placed"].cardinality == "one_to_many"
    assert back.objects["Order"].properties["status"].values == onto.objects["Order"].properties["status"].values
    assert back.objects["Sku"].properties["price"].type == "decimal"
    assert rep.summary()["unsupported"] == 0


def test_import_reports_what_it_cannot_map():
    pytest.importorskip("rdflib")
    from xgen_data_studio.exchange.importer import from_owl

    ttl = """@prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <https://example.org/v#> .
    ex:Loan a owl:Class ; rdfs:label "대출"@ko ; rdfs:subClassOf [ a owl:Restriction ] .
    ex:Product a owl:Class . ex:Loan rdfs:subClassOf ex:Product .
    ex:amount a owl:DatatypeProperty ; rdfs:domain ex:Loan ; rdfs:range <http://www.w3.org/2001/XMLSchema#decimal> .
    ex:Loan owl:disjointWith ex:Deposit ."""
    o, rep = from_owl(ttl)
    assert o.objects["Loan"].label == "대출" and o.objects["Loan"].parent == "Product"
    assert o.objects["Loan"].properties["amount"].type == "decimal"
    assert any("anonymous superclass" in u for u in rep.unsupported)
    assert any("disjointWith" in u for u in rep.unsupported)
