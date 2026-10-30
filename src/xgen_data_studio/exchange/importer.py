"""Import an OWL/RDFS vocabulary (FIBO, schema.org, GS1, an earlier export) as a starting definition."""
from __future__ import annotations

import re
from collections import Counter

from xgen_data_studio.exchange.owl import ExchangeReport
from xgen_data_studio.model import Interface, LinkType, ObjectType, Ontology, Property
from xgen_data_studio.rdf import OWL, RDFS, TYPE_OF_XSD, XSD

SKOS_MATCH = "http://www.w3.org/2004/02/skos/core#exactMatch"
DCT_SOURCE = "http://purl.org/dc/terms/source"
_CONSUMED = {SKOS_MATCH, DCT_SOURCE, RDFS + "isDefinedBy", RDFS + "label", RDFS + "comment", RDFS + "subClassOf", RDFS + "domain", RDFS + "range",
             OWL + "inverseOf", OWL + "versionInfo", OWL + "hasKey", OWL + "unionOf", OWL + "oneOf",
             "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://www.w3.org/1999/02/22-rdf-syntax-ns#first",
             "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"}


def _ident(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return s if s and not s[0].isdigit() else f"_{s}"


def _split(iri: str) -> tuple[str, str]:
    for sep in ("#", "/"):
        if sep in iri:
            head, tail = iri.rsplit(sep, 1)
            if tail:
                return head + sep, tail
    return "", iri


def from_owl(text: str, *, namespace: str = "", fmt: str = "turtle", name: str = "") -> tuple[Ontology, ExchangeReport]:
    try:
        import rdflib
        from rdflib.collection import Collection
    except ImportError as e:
        raise ImportError("OWL import needs the [rdf] extra (rdflib)") from e
    R = rdflib
    g = R.Graph().parse(data=text, format=fmt)
    rep = ExchangeReport()
    RDF_T, OWL_N, RDFS_N = R.RDF.type, R.Namespace(OWL), R.Namespace(RDFS)

    classes = {c for t in (OWL_N.Class, RDFS_N.Class) for c in g.subjects(RDF_T, t) if isinstance(c, R.URIRef)}
    if not namespace:
        counts = Counter(_split(str(c))[0] for c in classes)
        namespace = counts.most_common(1)[0][0] if counts else "https://example.org/imported#"

    def label(node) -> str:
        best = ""
        for lit in g.objects(node, RDFS_N.label):
            if getattr(lit, "language", None) == "ko":
                return str(lit)
            best = best or str(lit)
        return best

    names: dict = {}
    for c in sorted(classes, key=str):
        names[c] = _ident(_split(str(c))[1])

    def aligned(node, local: str) -> list[str]:
        out = [str(x) for x in g.objects(node, R.URIRef(SKOS_MATCH))]
        if str(node) != namespace + local:
            out.insert(0, str(node))
        return list(dict.fromkeys(out))

    def cite(node) -> str:
        return str(g.value(node, R.URIRef(DCT_SOURCE)) or "")

    def members(node) -> list:
        u = g.value(node, OWL_N.unionOf)
        return list(Collection(g, u)) if u is not None else []

    objects: dict[str, ObjectType] = {}
    for c, n in names.items():
        parents = [p for p in g.objects(c, RDFS_N.subClassOf) if p in names]
        restrictions = [p for p in g.objects(c, RDFS_N.subClassOf) if isinstance(p, R.BNode)]
        for _ in restrictions:
            rep.unsupported.append(f"class {n}: anonymous superclass (restriction or expression)")
        objects[n] = ObjectType(name=n, key="", properties={}, label=label(c),
                                description=str(g.value(c, RDFS_N.comment) or ""),
                                parent=names[parents[0]] if parents else "", cite=cite(c), aligned=aligned(c, n))
        if len(parents) > 1:
            rep.adjusted.append(f"class {n}: {len(parents)} superclasses -> kept {names[parents[0]]}")
        rep.preserved.append(f"class {n}")

    def domains(p) -> list[str]:
        out = []
        for d in g.objects(p, RDFS_N.domain):
            if d in names:
                out.append(names[d])
            else:
                out += [names[m] for m in members(d) if m in names]
        return out

    for p in sorted(set(g.subjects(RDF_T, OWL_N.DatatypeProperty)), key=str):
        n = _ident(_split(str(p))[1])
        rng = g.value(p, RDFS_N.range)
        values: list[str] = []
        if isinstance(rng, R.BNode) and g.value(rng, OWL_N.oneOf) is not None:
            values = [str(x) for x in Collection(g, g.value(rng, OWL_N.oneOf))]
            type_ = "enum"
        else:
            type_ = TYPE_OF_XSD.get(str(rng)[len(XSD):], "string") if rng is not None and str(rng).startswith(XSD) \
                else "string"
            if rng is not None and not str(rng).startswith(XSD):
                rep.adjusted.append(f"property {n}: range {rng} -> string")
        ds = domains(p)
        if not ds:
            rep.unsupported.append(f"property {n}: no class domain, not attached")
            continue
        for d in ds:
            objects[d].properties[n] = Property(n, type_, label=label(p), values=values, cite=cite(p),
                                                aligned=aligned(p, n))
        rep.preserved.append(f"property {n}")

    links: dict[str, LinkType] = {}
    inverses: dict[str, str] = {}
    for p in sorted(set(g.subjects(RDF_T, OWL_N.ObjectProperty)), key=str):
        n = _ident(_split(str(p))[1])
        inv = g.value(p, OWL_N.inverseOf)
        ds, rs = domains(p), [names[r] for r in g.objects(p, RDFS_N.range) if r in names]
        if inv is not None and not (ds and rs):
            inverses[_ident(_split(str(inv))[1])] = n
            continue
        if len(ds) != 1 or len(rs) != 1:
            rep.unsupported.append(f"object property {n}: needs exactly one domain and range class")
            continue
        types = set(g.objects(p, RDF_T))
        fun, ifun = OWL_N.FunctionalProperty in types, OWL_N.InverseFunctionalProperty in types
        card = {(True, True): "one_to_one", (True, False): "many_to_one", (False, True): "one_to_many"}.get(
            (fun, ifun), "many_to_many")
        links[n] = LinkType(n, ds[0], rs[0], card, label=label(p), transitive=OWL_N.TransitiveProperty in types,
                            symmetric=OWL_N.SymmetricProperty in types, cite=cite(p), aligned=aligned(p, n))
        if inv is not None:
            inverses.setdefault(n, _ident(_split(str(inv))[1]))
        rep.preserved.append(f"link {n}")
        rep.adjusted.append(f"link {n}: no join binding in OWL; add 'on' or 'via' before querying a database")
    for link, inv in inverses.items():
        if link in links and inv not in links:
            links[link].inverse = inv
            rep.preserved.append(f"inverse {inv}")

    for c, n in names.items():
        o = objects[n]
        key_list = g.value(c, OWL_N.hasKey)
        keys = [_ident(_split(str(k))[1]) for k in Collection(g, key_list)] if key_list is not None else []
        if keys and keys[0] in o.properties:
            o.key = keys[0]
        else:
            if "id" not in o.properties:
                o.properties = {"id": Property("id", "string", label="식별자"), **o.properties}
            o.key = "id"
            rep.adjusted.append(f"class {n}: no owl:hasKey -> key 'id'")
        if o.parent and o.parent in objects:
            for pn, pp in objects[o.parent].properties.items():
                o.properties.setdefault(pn, pp)

    ifaces: dict[str, Interface] = {}
    head = None
    for s in g.subjects(RDF_T, OWL_N.Ontology):
        head = s
    onto = Ontology(name=name or (label(head) if head is not None else "") or "imported", namespace=namespace,
                    objects=objects, links=links, interfaces=ifaces,
                    version=str(g.value(head, OWL_N.versionInfo) or "0.1.0") if head is not None else "0.1.0",
                    label=label(head) if head is not None else "")
    used = set()
    for s, p, o in g:
        if str(p) not in _CONSUMED:
            used.add(str(p))
    for p in sorted(used):
        rep.unsupported.append(f"predicate {p} not mapped")
    rep.adjusted.append("no source tables: bind each object type to a table before querying a database")
    return onto, rep
