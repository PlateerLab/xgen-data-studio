# Changelog

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
