"""xds: validate, translate, export and import ontologies; run, decide, test and serve a studio."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xgen_data_studio.model import Ontology


def _out(data: Any) -> None:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2, default=str)
    sys.stdout.buffer.write((text.rstrip("\n") + "\n").encode("utf-8"))


def _params(items: list[str]) -> dict:
    out = {}
    for x in items:
        k, v = x.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def _query(arg: str) -> Any:
    p = Path(arg)
    if p.suffix == ".json" and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    if arg.strip().startswith("{"):
        return json.loads(arg)
    return arg


def _text(arg: str) -> str:
    p = Path(arg)
    return p.read_text(encoding="utf-8") if p.exists() else arg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="xds", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="check an ontology definition")
    s.add_argument("ontology")

    s = sub.add_parser("translate", help="compile a query for a backend language")
    s.add_argument("ontology")
    s.add_argument("query", help="registered query name, IR JSON, or a .json file")
    s.add_argument("--to", required=True, help="sql[:dialect] | cypher | gql | sparql | sqlpgq")
    s.add_argument("--param", action="append", default=[])
    s.add_argument("--from", dest="source", choices=["ir", "sparql", "cypher"], default="ir")

    s = sub.add_parser("export", help="write the ontology in another format")
    s.add_argument("ontology")
    s.add_argument("--format", required=True, choices=["owl", "shacl", "r2rml", "pgq", "json", "yaml", "jdm",
                                                       "report"])
    s.add_argument("--decision", help="decision table for --format jdm")
    s.add_argument("-o", "--output")

    s = sub.add_parser("import-owl", help="start a definition from an OWL/RDFS vocabulary")
    s.add_argument("file")
    s.add_argument("--namespace", default="")
    s.add_argument("--format", default="turtle")
    s.add_argument("-o", "--output")

    for name, help_ in (("run", "run a query"), ("sparql", "run a SPARQL SELECT on any backend"),
                        ("cypher", "run a Cypher read query on any backend")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("config")
        s.add_argument("query")
        s.add_argument("--backend")
        s.add_argument("--param", action="append", default=[])
        s.add_argument("--role")
        s.add_argument("--principal", action="append", default=[])

    s = sub.add_parser("decide", help="evaluate a decision table for one object")
    s.add_argument("config")
    s.add_argument("decision")
    s.add_argument("key")
    s.add_argument("--param", action="append", default=[])

    for name, help_ in (("questions", "score the validation questions"),
                        ("rules", "derive links and list rule findings"),
                        ("shacl", "validate the projection with generated SHACL")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("config")

    s = sub.add_parser("conformance", help="run registered queries on several backends and compare")
    s.add_argument("config")
    s.add_argument("--backends", help="comma-separated; default all")

    s = sub.add_parser("catalog", help="the asset graph: what an agent sees, what a change touches")
    s.add_argument("config")
    s.add_argument("--impact")
    s.add_argument("--agent", action="append", default=[], help="name=role1,role2")
    s.add_argument("--sees")

    s = sub.add_parser("mcp", help="serve the studio to agents over MCP")
    s.add_argument("config")
    s.add_argument("--role")
    s.add_argument("--principal", action="append", default=[])
    s.add_argument("--read-only", action="store_true")
    s.add_argument("--transport", default="stdio")

    a = ap.parse_args(argv)

    if a.cmd == "validate":
        issues = Ontology.load(a.ontology).validate()
        _out({"ok": not issues, "issues": issues})
        return 0 if not issues else 1

    if a.cmd == "translate":
        from xgen_data_studio.compile.base import compiler_for

        onto = Ontology.load(a.ontology)
        if a.source == "sparql":
            from xgen_data_studio.parse.sparql import parse_sparql

            q = parse_sparql(_text(a.query), onto)
        elif a.source == "cypher":
            from xgen_data_studio.parse.cypher import parse_cypher

            q = parse_cypher(_text(a.query), onto)
        else:
            from xgen_data_studio.studio import Studio

            q = Studio(onto).query(_query(a.query))
        c = compiler_for(onto, a.to).compile(q)
        params = _params(a.param)
        _out({"language": c.language, "dialect": c.dialect, "text": c.text, "params": c.params,
              "preview": c.preview(params) if set(c.params) <= set(params) | set(c.literals) else None})
        return 0

    if a.cmd == "export":
        onto = Ontology.load(a.ontology)
        if a.format in ("owl", "report"):
            from xgen_data_studio.exchange.owl import to_owl

            ttl, rep = to_owl(onto)
            text = ttl if a.format == "owl" else json.dumps(rep.to_dict(), ensure_ascii=False, indent=2)
        elif a.format == "shacl":
            from xgen_data_studio.reason.shacl import to_shacl

            text = to_shacl(onto)
        elif a.format == "r2rml":
            from xgen_data_studio.exchange.r2rml import to_r2rml

            text = to_r2rml(onto)
        elif a.format == "pgq":
            from xgen_data_studio.compile.pgq import graph_ddl

            text = graph_ddl(onto)
        elif a.format == "jdm":
            from xgen_data_studio.decide.zen import to_jdm

            name = a.decision or next(iter(onto.decisions))
            text = json.dumps(to_jdm(onto.decisions[name]), ensure_ascii=False, indent=2)
        elif a.format == "json":
            text = json.dumps(onto.to_dict(), ensure_ascii=False, indent=2)
        else:
            import yaml

            text = yaml.safe_dump(onto.to_dict(), allow_unicode=True, sort_keys=False)
        if a.output:
            Path(a.output).write_text(text, encoding="utf-8")
            _out({"written": a.output})
        else:
            _out(text)
        return 0

    if a.cmd == "import-owl":
        from xgen_data_studio.exchange.importer import from_owl

        onto, rep = from_owl(Path(a.file).read_text(encoding="utf-8"), namespace=a.namespace, fmt=a.format)
        if a.output:
            onto.dump(a.output)
        _out({"written": a.output, "report": rep.to_dict(), **({} if a.output else {"ontology": onto.to_dict()})})
        return 0

    if a.cmd == "mcp":
        from xgen_data_studio.mcp_server import main as mcp_main

        args = [a.config, "--transport", a.transport] + (["--role", a.role] if a.role else [])
        args += sum((["--principal", p] for p in a.principal), []) + (["--read-only"] if a.read_only else [])
        mcp_main(args)
        return 0

    from xgen_data_studio.config import load_studio

    studio = load_studio(a.config)
    if a.cmd in ("run", "sparql", "cypher"):
        kw = {"backend": a.backend, "role": a.role, "principal": _params(a.principal)}
        if a.cmd == "run":
            res = studio.run(_query(a.query), _params(a.param), **kw)
        elif a.cmd == "sparql":
            res = studio.run_sparql(_text(a.query), _params(a.param), **kw)
        else:
            res = studio.run_cypher(_text(a.query), _params(a.param), **kw)
        from xgen_data_studio.tools import _jsonable

        _out({"backend": res.backend, "text": res.compiled.text,
              "rows": _jsonable(res.rows, res.columns, res.compiled.column_types)})
    elif a.cmd == "decide":
        _out(studio.decide(a.decision, a.key, _params(a.param)).to_dict())
    elif a.cmd == "questions":
        rep = studio.questions()
        _out(rep.to_dict())
        return 0 if rep.accuracy == 1.0 else 1
    elif a.cmd == "conformance":
        rep = studio.conformance(a.backends.split(",") if a.backends else None)
        _out(rep.to_dict())
        return 0 if rep.passed else 1
    elif a.cmd == "rules":
        from xgen_data_studio.projection import project
        from xgen_data_studio.reason.rules import run_rules

        _out(run_rules(studio.onto, studio.projection or project(studio.onto, studio.backend())).to_dict())
    elif a.cmd == "shacl":
        from xgen_data_studio.projection import project
        from xgen_data_studio.reason.shacl import validate

        rep = validate(studio.onto, studio.projection or project(studio.onto, studio.backend()))
        _out(rep.to_dict())
        return 0 if rep.conforms else 1
    elif a.cmd == "catalog":
        from xgen_data_studio.catalog import from_ontology

        cat = from_ontology(studio.onto, database=studio.source)
        for spec in a.agent:
            n, roles = spec.split("=", 1)
            cat.add_agent(n, roles=roles.split(","))
        if a.impact:
            _out([x.id for x in cat.impact(a.impact)])
        elif a.sees:
            _out([x.id for x in cat.sees(a.sees)])
        else:
            _out(cat.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
