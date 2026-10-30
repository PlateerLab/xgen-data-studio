import json

import pytest

from xgen_data_studio import ModelError, Ontology


def test_example_is_consistent(onto):
    assert onto.validate() == []
    assert onto.links["placed"].on == ("customer_id", "customer_id")
    assert onto.links["wishes"].via.table == "wishlists"
    assert onto.objects["Order"].states.allows("ORDERED", "PAID")
    assert not onto.objects["Order"].states.allows("DELIVERED", "PAID")


def test_round_trip_through_dict(onto):
    again = Ontology.from_dict(json.loads(json.dumps(onto.to_dict(), ensure_ascii=False)))
    assert again.to_dict() == onto.to_dict()
    assert again.validate() == []


def _base():
    return {
        "namespace": "https://example.org/t#",
        "objects": {
            "A": {"key": "id", "source": {"table": "a"}, "properties": {"id": "string", "n": "integer"}},
            "B": {"key": "id", "source": {"table": "b"}, "properties": {"id": "string", "a_id": "string"}},
        },
        "links": {"has": {"from": "A", "to": "B", "on": {"id": "a_id"}, "cardinality": "one_to_many"}},
    }


@pytest.mark.parametrize("patch, needle", [
    (lambda d: d["objects"]["A"].update(key="nope"), "key 'nope'"),
    (lambda d: d["objects"]["B"]["properties"].update(n="string"), "one name, one type"),
    (lambda d: d["links"]["has"].update(on={"id": "missing"}), "no property 'missing'"),
    (lambda d: d["links"]["has"].update(transitive=True), "from a type to itself"),
    (lambda d: d["links"].update(n={"from": "A", "to": "B"}), "clashes"),
    (lambda d: d.update(namespace="https://example.org/t"), "namespace"),
])
def test_validation_catches(patch, needle):
    d = _base()
    patch(d)
    issues = Ontology.from_dict(d).validate()
    assert any(needle in i for i in issues), issues


def test_check_raises(onto):
    d = onto.to_dict()
    d["objects"]["Order"]["key"] = "nope"
    with pytest.raises(ModelError):
        Ontology.from_dict(d).check()


def test_registered_query_params_must_be_declared(onto):
    d = onto.to_dict()
    d["queries"]["lowStock"]["params"] = {}
    assert any("parameter 'threshold' is not declared" in i for i in Ontology.from_dict(d).validate())
