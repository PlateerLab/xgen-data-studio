import pytest

from xgen_data_studio.compile.base import compiler_for
from xgen_data_studio.ir import Query
from xgen_data_studio.parse.cypher import parse_cypher
from xgen_data_studio.parse.sparql import ParseError


def test_compiled_queries_read_back(studio):
    pytest.importorskip("rdflib")
    from xgen_data_studio.parse.sparql import parse_sparql

    onto = studio.onto
    for name, (q, params) in studio.registered().items():
        base = studio.run(q, params).rows
        sparql = compiler_for(onto, "sparql").compile(q).bind(params)[0]
        assert studio.run(parse_sparql(sparql, onto)).rows == base, name
        cypher = compiler_for(onto, "cypher").compile(q).preview(params)
        assert studio.run(parse_cypher(cypher, onto)).rows == base, name


def test_hand_written_cypher_runs_on_sql(studio):
    q = parse_cypher("""
        MATCH (c:Customer)-[:placed]->(o:Order)-[:hasItem]->(i:OrderItem)
        WHERE o.status = 'DELIVERED' AND NOT EXISTS { MATCH (i)-[:hasClaim]->(:Claim) }
        RETURN c.name AS customer, count(i) AS items ORDER BY customer
    """, studio.onto)
    assert studio.run(q).rows == [("김하늘", 1), ("이도윤", 2)]


def test_cypher_params_and_lists(studio):
    q = parse_cypher("MATCH (s:Sku) WHERE s.stock < $t AND s.size IN ['M', 'L'] RETURN s.sku_id ORDER BY sku_id",
                     studio.onto)
    assert studio.run(q, {"t": 5}).rows == [("S1",), ("S3",)]


def test_hand_written_sparql_runs_on_sql(studio):
    pytest.importorskip("rdflib")
    from xgen_data_studio.parse.sparql import parse_sparql

    q = parse_sparql("""PREFIX ex: <https://example.org/commerce#>
        SELECT ?name (COUNT(?p) AS ?wished)
        WHERE { ?c a ex:Customer ; ex:name ?name ; ex:wishes ?p . ?p a ex:Product . }
        GROUP BY ?name ORDER BY ?name""", studio.onto)
    assert studio.run(q).rows == [("김하늘", 2), ("이도윤", 1)]
    q = parse_sparql("""PREFIX ex: <https://example.org/commerce#>
        SELECT ?a WHERE { ?k a ex:Category ; ex:category_id "K3" . ?k ex:broader+ ?x . ?x a ex:Category ;
        ex:name ?a . } ORDER BY ?a""", studio.onto)
    assert studio.run(q).rows == [("상의",), ("의류",)]


def test_reader_errors(onto):
    with pytest.raises(ParseError):
        parse_cypher("MATCH (x:Nope) RETURN x.y", onto)
    with pytest.raises(ParseError):
        parse_cypher("MATCH (o:Order) RETURN o.status ORDER BY elsewhere", onto)
    pytest.importorskip("rdflib")
    from xgen_data_studio.parse.sparql import parse_sparql

    with pytest.raises(ParseError):
        parse_sparql("SELECT ?x WHERE { ?x a <https://other.org/X> }", onto)


def test_translate_between_languages(studio):
    q = parse_cypher("MATCH (o:Order) WHERE o.status <> 'CANCELLED' RETURN o.status, count(o) AS n", studio.onto)
    assert isinstance(q, Query)
    sparql = compiler_for(studio.onto, "sparql").compile(q).text
    assert "GROUP BY ?o__status" in sparql
