"""OWL 2 export of the ontology (classes, data and object properties) with a report of what OWL cannot hold."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from xgen_data_studio.model import Ontology
from xgen_data_studio.rdf import OWL, RDF_TYPE, RDFS, XSD, XSD_OF, Turtle, escape, literal


@dataclass
class ExchangeReport:
    preserved: list[str] = field(default_factory=list)
    adjusted: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {"preserved": len(self.preserved), "adjusted": len(self.adjusted),
                "unsupported": len(self.unsupported)}

    def to_dict(self) -> dict:
        return {"summary": self.summary(), **asdict(self)}


def _labels(text: str, lang: str = "ko") -> list[tuple[str, str]]:
    return [(RDFS + "label", literal(text, "string", lang))] if text else []


def to_owl(onto: Ontology) -> tuple[str, ExchangeReport]:
    rep = ExchangeReport()
    ns = onto.namespace
    tt = Turtle({"owl": OWL, "rdfs": RDFS, "xsd": XSD, "ex": ns})
    head = ns.rstrip("#/")
    tt.add(head, [(RDF_TYPE, OWL + "Ontology"), (OWL + "versionInfo", literal(onto.version, "string")),
                  *_labels(onto.label or onto.name)])
    for i in onto.interfaces.values():
        tt.add(ns + i.name, [(RDF_TYPE, OWL + "Class"), *_labels(i.label)])
        rep.adjusted.append(f"interface {i.name} -> owl:Class (implementers become subclasses)")
    for o in onto.objects.values():
        pairs = [(RDF_TYPE, OWL + "Class"), *_labels(o.label)]
        if o.description:
            pairs.append((RDFS + "comment", literal(o.description, "string", "ko")))
        for parent in ([o.parent] if o.parent else []) + o.implements:
            pairs.append((RDFS + "subClassOf", ns + parent))
        tt.add(ns + o.name, pairs)
        rep.preserved.append(f"class {o.name}")
        if o.states:
            rep.unsupported.append(f"state machine of {o.name} (kept in the studio definition)")
        if o.table:
            rep.adjusted.append(f"binding of {o.name} to table {o.table} -> export R2RML instead")

    domains: dict[str, list[str]] = {}
    props = {}
    for o in onto.objects.values():
        for p in o.properties.values():
            domains.setdefault(p.name, []).append(o.name)
            props.setdefault(p.name, p)
    for name, p in props.items():
        pairs = [(RDF_TYPE, OWL + "DatatypeProperty"), (RDF_TYPE, OWL + "FunctionalProperty"), *_labels(p.label),
                 (RDFS + "range", XSD + XSD_OF[p.type])]
        ds = domains[name]
        if len(ds) == 1:
            pairs.append((RDFS + "domain", ns + ds[0]))
        else:
            union = " ".join(f"ex:{d}" for d in ds)
            pairs.append((RDFS + "domain", f"[ a owl:Class ; owl:unionOf ( {union} ) ]"))
            rep.adjusted.append(f"property {name} is shared by {ds} -> rdfs:domain is their union")
        if p.type == "enum":
            items = " ".join(f'"{escape(v)}"' for v in p.values)
            pairs[3] = (RDFS + "range", f"[ a rdfs:Datatype ; owl:oneOf ( {items} ) ]")
            rep.adjusted.append(f"enum {name} -> datatype enumeration of strings")
        tt.add(ns + name, pairs)
        rep.preserved.append(f"property {name}")

    for lk in onto.links.values():
        pairs = [(RDF_TYPE, OWL + "ObjectProperty"), *_labels(lk.label), (RDFS + "domain", ns + lk.source),
                 (RDFS + "range", ns + lk.target)]
        if lk.transitive and lk.cardinality != "many_to_many":
            rep.adjusted.append(f"link {lk.name}: transitive, so its {lk.cardinality} limit stays in SHACL "
                                "(OWL 2 forbids functional transitive properties)")
        elif lk.cardinality in ("many_to_one", "one_to_one"):
            pairs.append((RDF_TYPE, OWL + "FunctionalProperty"))
        if lk.cardinality in ("one_to_many", "one_to_one") and not lk.transitive:
            pairs.append((RDF_TYPE, OWL + "InverseFunctionalProperty"))
        if lk.transitive:
            pairs.append((RDF_TYPE, OWL + "TransitiveProperty"))
        if lk.symmetric:
            pairs.append((RDF_TYPE, OWL + "SymmetricProperty"))
        tt.add(ns + lk.name, pairs)
        rep.preserved.append(f"link {lk.name}")
        if lk.inverse:
            tt.add(ns + lk.inverse, [(RDF_TYPE, OWL + "ObjectProperty"), (OWL + "inverseOf", ns + lk.name)])
            rep.preserved.append(f"inverse {lk.inverse}")
        if lk.required:
            rep.adjusted.append(f"required link {lk.name} -> SHACL sh:minCount (OWL is open-world)")

    for kind, coll in (("decision table", onto.decisions), ("action", onto.actions), ("role", onto.roles),
                       ("registered query", onto.queries)):
        for n in coll:
            rep.unsupported.append(f"{kind} {n} (kept in the studio definition)")
    if onto.questions:
        rep.unsupported.append(f"{len(onto.questions)} validation questions (kept in the studio definition)")
    for a, b in onto.exclusive:
        rep.unsupported.append(f"exclusive links {a} / {b} (checked by the studio rules)")
    return tt.text(), rep
