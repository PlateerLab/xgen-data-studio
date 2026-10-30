"""One query, every backend language; then the same answer from SQL and SPARQL, a decision with evidence."""
from datetime import datetime
from pathlib import Path

from xgen_data_studio import Ontology
from xgen_data_studio.backends.rdf import RdflibBackend
from xgen_data_studio.backends.sql import SqliteBackend
from xgen_data_studio.studio import Studio

HERE = Path(__file__).parent

onto = Ontology.load(HERE / "ontology.yaml").check()
studio = Studio(onto, now=lambda: datetime(2026, 10, 30, 12, 0))
studio.add_backend("source", SqliteBackend()).script((HERE / "seed.sql").read_text(encoding="utf-8"))
studio.add_backend("graph", RdflibBackend())
studio.project()

for target in ("sql:postgres", "sql:mysql", "cypher", "gql", "sparql", "sqlpgq"):
    print(f"--- {target}\n{studio.translate('revenueByCategory', target).text}\n")

print("source:", studio.run("revenueByCategory").rows)
print("graph: ", studio.run("revenueByCategory", backend="graph").rows)
print("conformance:", studio.conformance().summary())

r = studio.decide("returnEligibility", "I1001")
print("decision:", r.outputs, "rule", r.matched)
for e in r.evidence:
    print(f"  {e.input} = {e.value!r}  <- {e.source}")
print("questions:", studio.questions().accuracy)
