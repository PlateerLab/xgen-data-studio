import sqlite3

import pytest

from xgen_data_studio.backends.base import Capabilities
from xgen_data_studio.backends.graph import CallableBackend, Neo4jBackend
from xgen_data_studio.backends.sql import DbApiBackend
from xgen_data_studio.compile.base import CompileError
from xgen_data_studio.projection import Projection, project


def test_graph_backend_agrees_with_source(graph_studio):
    rep = graph_studio.conformance()
    assert rep.passed, rep.summary()
    assert rep.summary()["agree"] == len(graph_studio.onto.queries)


def test_dbapi_paramstyles(onto):
    conn = sqlite3.connect(":memory:")
    conn.executescript("CREATE TABLE skus (sku_id TEXT, size TEXT, stock INTEGER);"
                       "INSERT INTO skus VALUES ('S1', 'M', 1), ('S2', 'L', 9);")
    b = DbApiBackend(conn, "sqlite", paramstyle="qmark")
    c = b.compiler(onto).compile(onto.queries["lowStock"].query)
    assert b.execute(c, {"threshold": 5}).rows == [("S1", 1)]
    fmt = DbApiBackend(conn, "postgres", paramstyle="format")
    assert fmt._text("a = ? AND b LIKE 'x?%'") == "a = %s AND b LIKE 'x?%%'"
    num = DbApiBackend(conn, "oracle", paramstyle="numeric")
    assert num._text("a = ? AND b = ?") == "a = :1 AND b = :2"


def test_projection_round_trip(onto, source):
    proj = project(onto, source)
    assert len(proj.nodes) == 25 and len(proj.edges) == 30
    assert proj.nodes[("Category", "K4")]["returnable"] is False
    nt = proj.ntriples(onto)
    assert "<https://example.org/commerce#OrderItem/I1001> <https://example.org/commerce#hasClaim>" not in nt
    assert '"2026-10-25T15:00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime>' in nt


def test_change_set(onto, source):
    before = project(onto, source)
    source.run("UPDATE order_items SET item_status = 'RETURNED' WHERE item_id = 'I1002'")
    source.run("DELETE FROM wishlists WHERE customer_id = 'C002'")
    after = project(onto, source)
    cs = before.diff(after)
    assert cs.summary() == {"added": 0, "removed": 0, "changed": 1, "added_edges": 0, "removed_edges": 1}
    upd = cs.sparql_update(onto)
    assert upd.startswith("DELETE DATA") and "INSERT DATA" in upd and '"RETURNED"' in upd
    assert cs.cypher(onto)[0][0].startswith("MATCH (a:`Customer`")
    assert Projection().diff(Projection()).empty


def test_incremental_projection_into_graph(graph_studio):
    graph_studio.backend("source").run("UPDATE skus SET stock = 1 WHERE sku_id = 'S2'")
    rep = graph_studio.project()
    assert rep["graph"]["changes"]["changed"] == 1
    assert graph_studio.run("lowStock", {"threshold": 5}, backend="graph").rows == [("S1", 3), ("S2", 1), ("S3", 2)]


class _FakeDriver:
    def __init__(self):
        self.calls = []

    def execute_query(self, text, params, **kw):
        self.calls.append((text, params, kw))
        return ([{"sku_id": "S1", "stock": 3}], None, None)


def test_neo4j_backend_with_a_fake_driver(onto, source):
    d = _FakeDriver()
    b = Neo4jBackend(d, database="neo4j")
    c = b.compiler(onto).compile(onto.queries["lowStock"].query)
    assert b.execute(c, {"threshold": 5}).rows == [("S1", 3)]
    text, params, kw = d.calls[0]
    assert params == {"threshold": 5, "_v1": ["M", "L"]} and kw == {"database_": "neo4j"}
    from xgen_data_studio.projection import load

    load(onto, project(onto, source), b)
    assert d.calls[1][0] == "MATCH (n) DETACH DELETE n"
    assert any("MERGE (a)-[:`hasItem`]->(b)" in t for t, _, _ in d.calls)


def test_callable_backend_and_capabilities(studio):
    seen = []
    caps = Capabilities("gql", "iso", contains=False, optional=False)
    studio.add_backend("spanner", CallableBackend("spanner", caps, lambda t, a: seen.append((t, a)) or [("x", 1)]))
    assert studio.run("wishlistCount", backend="spanner").rows == [("x", 1)]
    assert seen[0][0].startswith("MATCH (c:`Customer`)-[:`wishes`]->(p:`Product`)")
    with pytest.raises(CompileError, match="contains"):
        studio.run("searchProducts", {"text": "니트"}, backend="spanner")
    rep = studio.conformance(["source", "spanner"])
    assert any(o.error.startswith("unsupported") for q in rep.queries for o in q.outcomes.values())
