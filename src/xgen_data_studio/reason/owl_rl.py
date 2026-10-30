"""OWL 2 RL materialization with owlrl: the ontology's OWL export plus a projection, closed under RL rules."""
from __future__ import annotations

from xgen_data_studio.model import Ontology
from xgen_data_studio.projection import Projection
from xgen_data_studio.rdf import RDF_TYPE, Iris


def materialize(onto: Ontology, projection: Projection) -> list[tuple[str, str, str]]:
    """Return the derived data triples (subject, predicate, object) as plain IRIs."""
    try:
        import owlrl
        import rdflib
    except ImportError as e:
        raise ImportError("OWL RL materialization needs the [owl] extra (owlrl)") from e
    from xgen_data_studio.exchange.owl import to_owl

    g = rdflib.Graph()
    g.parse(data=to_owl(onto)[0], format="turtle")
    g.parse(data=projection.ntriples(onto), format="turtle")
    before = set(g)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(g)
    ir = Iris(onto)
    out = []
    for s, p, o in set(g) - before:
        if not isinstance(s, rdflib.URIRef) or ir.key_of(str(s)) is None:
            continue
        if str(p) == RDF_TYPE:
            if ir.local(str(o)) in onto.objects:
                out.append((str(s), str(p), str(o)))
        elif ir.local(str(p)) is not None and isinstance(o, rdflib.URIRef) and ir.key_of(str(o)):
            out.append((str(s), str(p), str(o)))
    return sorted(out)
