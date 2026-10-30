from datetime import datetime
from pathlib import Path

import pytest

from xgen_data_studio import Ontology
from xgen_data_studio.backends.sql import SqliteBackend
from xgen_data_studio.studio import Studio

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "commerce"
NOW = datetime(2026, 10, 30, 12, 0)


@pytest.fixture
def onto() -> Ontology:
    return Ontology.load(EXAMPLE / "ontology.yaml")


@pytest.fixture
def source() -> SqliteBackend:
    b = SqliteBackend()
    b.script((EXAMPLE / "seed.sql").read_text(encoding="utf-8"))
    return b


@pytest.fixture
def studio(onto, source) -> Studio:
    st = Studio(onto, now=lambda: NOW)
    st.add_backend("source", source)
    return st


@pytest.fixture
def graph_studio(studio) -> Studio:
    pytest.importorskip("rdflib")
    from xgen_data_studio.backends.rdf import RdflibBackend

    studio.add_backend("graph", RdflibBackend())
    studio.project()
    return studio
