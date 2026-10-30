"""SHACL shapes generated from the ontology, validated with pySHACL against a projection."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from xgen_data_studio.model import Ontology
from xgen_data_studio.projection import Projection
from xgen_data_studio.rdf import SH, XSD, XSD_OF, Iris, Turtle, escape, iri


def to_shacl(onto: Ontology) -> str:
    ir = Iris(onto)
    tt = Turtle({"sh": SH, "xsd": XSD, "ex": onto.namespace})
    for o in onto.objects.values():
        pairs = [("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", SH + "NodeShape"),
                 (SH + "targetClass", ir.cls(o.name))]
        for p in o.properties.values():
            body = [f"sh:path {iri(ir.prop(p.name))}", f"sh:datatype xsd:{XSD_OF[p.type]}", "sh:maxCount 1"]
            if p.required or p.name == o.key:
                body.append("sh:minCount 1")
            if p.type == "enum" and p.values:
                body.append("sh:in (" + " ".join(f'"{escape(v)}"' for v in p.values) + ")")
            pairs.append((SH + "property", "[ " + " ; ".join(body) + " ]"))
        for lk in onto.links.values():
            if lk.source != o.name:
                continue
            body = [f"sh:path {iri(ir.link(lk.name))}", f"sh:class {iri(ir.cls(lk.target))}"]
            if lk.cardinality in ("many_to_one", "one_to_one"):
                body.append("sh:maxCount 1")
            if lk.required:
                body.append("sh:minCount 1")
            pairs.append((SH + "property", "[ " + " ; ".join(body) + " ]"))
        tt.add(onto.namespace + o.name + "Shape", pairs)
    return tt.text()


@dataclass
class ShaclReport:
    conforms: bool
    results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def validate(onto: Ontology, projection: Projection, shapes: str | None = None) -> ShaclReport:
    try:
        import rdflib
        from pyshacl import validate as shacl_validate
    except ImportError as e:
        raise ImportError("SHACL validation needs the [shacl] extra (pyshacl)") from e
    data = rdflib.Graph().parse(data=projection.ntriples(onto), format="turtle")
    sg = rdflib.Graph().parse(data=shapes or to_shacl(onto), format="turtle")
    conforms, report, _ = shacl_validate(data, shacl_graph=sg, inference="none")
    sh = rdflib.Namespace(SH)
    results = []
    for r in report.subjects(rdflib.RDF.type, sh.ValidationResult):
        results.append({"focus": str(report.value(r, sh.focusNode)),
                        "path": str(report.value(r, sh.resultPath) or ""),
                        "message": str(report.value(r, sh.resultMessage) or ""),
                        "constraint": str(report.value(r, sh.sourceConstraintComponent) or "").rsplit("#", 1)[-1]})
    results.sort(key=lambda x: (x["focus"], x["path"]))
    return ShaclReport(bool(conforms), results)
