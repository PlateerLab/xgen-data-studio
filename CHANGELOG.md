# Changelog

## 0.2.0

- Modules: domain knowledge packaged as common concepts, domains, industry extensions, a customer's
  differences and database bindings; composed in requirement order with the origin of every element,
  extended (properties, enum values, columns, decision rules ahead of or after the standard ones, role scope)
  and trimmed (`remove`); attach and detach at run time, with the impact of a detach shown first.
- Library: versioned packages kept apart on disk; list, create, save a version, diff, delete (refused while
  another package requires it), resolve requirements, import an OWL standard as a package.
- Concepts: a type without a table is queried through its bound subtypes (SQL `UNION ALL`; SPARQL and Cypher by
  the concept's type), so one question reaches every domain that specialises the concept.
- Provenance: `cite` on types, properties, links, decisions, rules and actions; `aligned` IRIs to public
  vocabularies; OWL export with `skos:exactMatch`, `dcterms:source` and `rdfs:isDefinedBy`; import keeps the source IRIs.
- Database check: tables, columns and types against the definition, duplicate keys, missing required values,
  enum values the definition does not know, links that point at nothing (`xds bindings`).
- The studio page gains the ontology library tab; the schema graph shows each type's module and its concepts.
- Example library: common concepts, commerce, commerce bindings, fashion, food, a customer overlay, finance
  aligned to FIBO, finance bindings.

## 0.1.0

- Metamodel: object types, properties, links (on / via), interfaces, state machines, decision tables, actions,
  roles with row filters, registered queries, validation questions; JSON and YAML, with consistency checks.
- Ontology query IR with checking (link direction, inverse names, types, parameters, connectivity).
- Compilers: SQL (PostgreSQL, SQLite; other dialects through sqlglot), Cypher 25, ISO GQL, SPARQL 1.1, SQL/PGQ,
  and CREATE PROPERTY GRAPH for the bound tables.
- Backends: SQLite, any DB-API connection, rdflib, SPARQL 1.1 endpoints, Neo4j, a callable adapter; capabilities.
- Projection of source rows to RDF and property graphs, with change sets for incremental loads.
- Readers for SPARQL and Cypher into the IR, so a query in either runs on any backend.
- Decision tables (first / collect / unique) with evidence, GoRules JDM export and ZEN evaluation.
- Actions with checks, human approval, SQL write-back and an audit trail; role scoping for queries and tools.
- Rules (inverse, symmetric, transitive, shape checks), SHACL generation and validation, OWL RL materialization.
- OWL and R2RML export with an exchange report; OWL/RDFS import.
- Asset catalog: what an agent sees, what a change touches, what nobody uses.
- LLM assist: schema card, IR generation with check-and-repair.
- Conformance runs across backends, `xds` CLI and an MCP server.
- `xds preview`: a studio page (ontology, one query on every backend, a decision, the data map) built from
  live results; `tools/render_screens.py` captures it for the README.
