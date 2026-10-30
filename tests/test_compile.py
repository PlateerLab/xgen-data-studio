import pytest

from xgen_data_studio.compile.base import CompileError, compiler_for
from xgen_data_studio.compile.pgq import graph_ddl


def _q(onto, name):
    return onto.queries[name].query


def test_sql_runs_every_registered_query(studio):
    expected = {
        "ordersOfCustomer": [("O1", "DELIVERED", "2026-10-20T10:00:00"), ("O2", "SHIPPED", "2026-10-27T09:30:00")],
        "revenueByCategory": [("니트", 177000.0, 3), ("상의", 19000.0, 1), ("속옷", 15000.0, 1)],
        "deliveredWithoutClaim": [("I1001", "O1", "2026-10-25T15:00:00"), ("I1003", "O3", "2026-10-18T10:00:00"),
                                  ("I1004", "O3", "2026-10-18T10:00:00")],
        "categoryAncestors": [("상의",), ("의류",)],
        "ordersPerCustomer": [("김하늘", 2), ("이도윤", 2), ("박서연", 0)],
        "searchProducts": [("P1", "울 니트 스웨터")],
        "wishlistCount": [("김하늘", 2), ("이도윤", 1)],
        "lowStock": [("S1", 3), ("S3", 2)],
    }
    for name, (q, params) in studio.registered().items():
        rows = studio.run(q, params).rows
        if name in expected:
            assert rows == expected[name], name


def test_sql_binds_literals_as_parameters(onto):
    c = compiler_for(onto, "sql:sqlite").compile(_q(onto, "lowStock"))
    assert "'M'" not in c.text and c.params == ["threshold", "_v1", "_v2"]
    text, args = c.bind({"threshold": "5"})
    assert args == (5, "M", "L")


def test_recursive_cte_for_hops(onto):
    c = compiler_for(onto, "sql:postgres").compile(_q(onto, "categoryAncestors"))
    assert c.text.startswith("WITH RECURSIVE") and "d < 3" in c.text


@pytest.mark.parametrize("dialect, needle", [("mysql", "`"), ("oracle", '"skus"'), ("tsql", "["),
                                             ("snowflake", '"skus"'), ("bigquery", "`")])
def test_other_sql_dialects(onto, dialect, needle):
    pytest.importorskip("sqlglot")
    c = compiler_for(onto, f"sql:{dialect}").compile(_q(onto, "lowStock"))
    assert needle in c.text


def test_unknown_dialect(onto):
    pytest.importorskip("sqlglot")
    with pytest.raises(CompileError):
        compiler_for(onto, "sql:nosuchdb").compile(_q(onto, "lowStock"))


def test_cypher(onto):
    c = compiler_for(onto, "cypher").compile(_q(onto, "deliveredWithoutClaim"))
    assert "(i:`OrderItem`)<-[:`hasItem`]-(o:`Order`)" in c.text
    assert "NOT EXISTS { MATCH (i)-[:`hasClaim`]->(c:`Claim`) }" in c.text
    c = compiler_for(onto, "cypher").compile(_q(onto, "categoryAncestors"))
    assert "[:`broader`*1..3]" in c.text and "WITH DISTINCT" in c.text
    c = compiler_for(onto, "cypher").compile(_q(onto, "ordersPerCustomer"))
    assert "OPTIONAL MATCH" in c.text and "`orders` IS NULL, `orders` DESC" in c.text


def test_gql_dialect(onto):
    c = compiler_for(onto, "gql").compile(_q(onto, "revenueByCategory"))
    assert "GROUP BY `category`" in c.text and "NULLS LAST" in c.text
    c = compiler_for(onto, "gql").compile(_q(onto, "categoryAncestors"))
    assert "ANY (k:`Category`)-[:`broader`]->{1,3}(a:`Category`)" in c.text
    with pytest.raises(CompileError, match="substring"):
        compiler_for(onto, "gql").compile(_q(onto, "searchProducts"))


def test_sparql(onto):
    c = compiler_for(onto, "sparql").compile(_q(onto, "lowStock"))
    text, args = c.bind({"threshold": 5})
    assert args is None and "?s__stock < 5" in text and '"M"' in text


def test_sqlpgq(onto):
    c = compiler_for(onto, "sqlpgq").compile(_q(onto, "revenueByCategory"))
    assert "FROM GRAPH_TABLE" in c.text and "COLUMNS (" in c.text and "GROUP BY gt.\"category\"" in c.text
    with pytest.raises(CompileError, match="OPTIONAL"):
        compiler_for(onto, "sqlpgq").compile(_q(onto, "ordersPerCustomer"))
    with pytest.raises(CompileError, match="EXISTS"):
        compiler_for(onto, "sqlpgq").compile(_q(onto, "deliveredWithoutClaim"))


def test_property_graph_ddl(onto):
    ddl = graph_ddl(onto)
    assert ddl.startswith('CREATE PROPERTY GRAPH "commerce_sample"')
    assert '"order_items" AS "hasItem" KEY ("item_id") SOURCE KEY ("order_id") REFERENCES "Order"' in ddl
    assert '"wishlists" AS "wishes"' in ddl


def test_preview_shows_values(onto):
    c = compiler_for(onto, "cypher").compile(_q(onto, "lowStock"))
    assert "5" in c.preview({"threshold": 5}) and "['M', 'L']" in c.preview({"threshold": 5})
