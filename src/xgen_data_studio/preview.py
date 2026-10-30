"""A static studio page built from a live studio: the ontology, one query on every backend, a decision, the data map."""
from __future__ import annotations

import json
from collections import defaultdict
from html import escape
from typing import Any

from xgen_data_studio.actions import Actor
from xgen_data_studio.catalog import from_ontology
from xgen_data_studio.compile.base import CompileError
from xgen_data_studio.conformance import normalize_rows
from xgen_data_studio.studio import Studio

TARGETS = [("sql:postgres", "PostgreSQL"), ("sql:mysql", "MySQL"), ("sql:oracle", "Oracle"),
           ("cypher", "Cypher 25"), ("gql", "GQL"), ("sparql", "SPARQL 1.1"), ("sqlpgq", "SQL/PGQ")]
MODULE_COLOR = {"core": "#7a5af8", "domain": "#1a73e8", "industry": "#0f9d8a", "customer": "#d9822b",
                "binding": "#8a96a5"}
MODULE_KIND = {"core": "공통 개념", "domain": "도메인", "industry": "업종 확장", "customer": "고객사 차이",
               "binding": "바인딩"}
KIND_LABEL = {"column": "컬럼", "property": "속성", "query": "등록 질의", "decision": "결정", "action": "액션",
              "role": "역할", "agent": "에이전트", "link": "관계", "object": "객체", "table": "테이블", "file": "파일",
              "collection": "컬렉션", "folder": "폴더", "database": "데이터베이스"}

CSS = """
:root { --navy:#13213c; --blue:#1a73e8; --blue-soft:#e8f0fd; --blue-line:#c7dafb; --ink:#1b2330; --muted:#5f6b7a;
  --line:#e1e6ed; --panel:#f6f8fb; --bg:#eef1f6; --ok:#1e9e5a; --ok-soft:#e5f5ec; --warn:#b7791f; --warn-soft:#fdf3e1;
  --bad:#d93025; --code:#0f1a2e; }
* { box-sizing:border-box; }
html, body { margin:0; background:var(--bg); }
body { font-family:"Pretendard","Malgun Gothic",-apple-system,sans-serif; color:var(--ink); font-size:14px;
  -webkit-font-smoothing:antialiased; word-break:keep-all; }
.screen { width:1440px; height:900px; margin:24px auto; background:#fff; border-radius:14px; overflow:hidden;
  display:grid; grid-template-columns:232px 1fr; grid-template-rows:56px 1fr; box-shadow:0 10px 40px rgba(19,33,60,.12); }
body.single .screen { display:none; margin:0; border-radius:0; box-shadow:none; }
body.single .screen.on { display:grid; }
.top { grid-column:1 / 3; display:flex; align-items:center; gap:14px; padding:0 22px; border-bottom:1px solid var(--line); }
.brand { display:flex; align-items:center; gap:10px; font-weight:800; font-size:16px; color:var(--navy);
  white-space:nowrap; }
.logo { width:28px; height:28px; border-radius:8px; background:linear-gradient(135deg,#1a73e8,#13213c);
  display:grid; place-items:center; color:#fff; font-size:13px; font-weight:800; }
.top .chip { margin-left:4px; }
.top .grow { flex:1; }
.top .who { display:flex; align-items:center; gap:8px; color:var(--muted); font-size:13px; }
.avatar { width:28px; height:28px; border-radius:50%; background:#dbe4f3; display:grid; place-items:center;
  font-size:12px; font-weight:700; color:var(--navy); }
.side { background:var(--panel); border-right:1px solid var(--line); padding:18px 12px; }
.side h6 { margin:6px 10px 8px; font-size:11px; letter-spacing:.06em; color:#8a96a5; font-weight:700; }
.nav { display:flex; align-items:center; gap:10px; padding:9px 12px; border-radius:9px; color:#3a4656;
  font-weight:600; font-size:14px; margin-bottom:2px; cursor:pointer; text-decoration:none; }
.nav svg { width:18px; height:18px; stroke:currentColor; fill:none; stroke-width:1.9; stroke-linecap:round;
  stroke-linejoin:round; flex:none; }
.nav.on { background:#fff; color:var(--blue); box-shadow:0 1px 3px rgba(19,33,60,.08); }
.nav .n { margin-left:auto; font-size:11px; color:#8a96a5; font-weight:700; }
.side .foot { position:relative; margin-top:22px; padding:12px; border-radius:10px; background:#fff;
  border:1px solid var(--line); font-size:12px; color:var(--muted); line-height:1.5; }
.side .foot b { color:var(--ink); display:block; font-size:13px; margin-bottom:2px; }
.main { padding:22px 26px; overflow:hidden; display:flex; flex-direction:column; gap:16px; }
.head { display:flex; align-items:flex-end; gap:14px; }
.head h1 { margin:0; font-size:22px; font-weight:800; letter-spacing:-.3px; }
.head .sub { color:var(--muted); font-size:13px; margin-top:3px; }
.head .right { margin-left:auto; display:flex; gap:8px; }
.btn { border:1px solid var(--line); background:#fff; border-radius:9px; padding:8px 14px; font-weight:700;
  font-size:13px; color:var(--ink); }
.btn.primary { background:var(--blue); color:#fff; border-color:var(--blue); }
.btn.ghost { color:var(--muted); }
.chip { display:inline-flex; align-items:center; gap:5px; font-size:12px; padding:3px 9px; border-radius:999px;
  background:#fff; border:1px solid var(--line); color:#3a4656; font-weight:600; white-space:nowrap; }
.chip.b { background:var(--blue-soft); border-color:var(--blue-line); color:#15509f; }
.chip.ok { background:var(--ok-soft); border-color:#bfe5cf; color:#137a44; }
.chip.warn { background:var(--warn-soft); border-color:#f2d9a8; color:#8a5a12; }
.chip.n { background:var(--navy); border-color:var(--navy); color:#fff; }
.dot { width:7px; height:7px; border-radius:50%; background:var(--ok); display:inline-block; }
.stats { display:grid; grid-template-columns:repeat(6,1fr); gap:10px; }
.stat { border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
.stat b { display:block; font-size:22px; font-weight:800; color:var(--navy); line-height:1.1; }
.stat span { color:var(--muted); font-size:12px; font-weight:600; }
.card { border:1px solid var(--line); border-radius:12px; background:#fff; min-width:0; overflow:hidden;
  display:flex; flex-direction:column; }
.card > .ch { display:flex; align-items:center; gap:8px; padding:12px 16px; border-bottom:1px solid var(--line);
  font-weight:800; font-size:14px; }
.card > .ch .right { margin-left:auto; display:flex; gap:6px; align-items:center; }
.card > .cb { padding:14px 16px; min-height:0; overflow:hidden; }
.grid { display:grid; gap:16px; min-height:0; flex:1; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th { text-align:left; color:#8a96a5; font-weight:700; font-size:11.5px; letter-spacing:.03em; padding:7px 10px;
  border-bottom:1px solid var(--line); background:var(--panel); }
td { padding:7px 10px; border-bottom:1px solid #f0f2f6; vertical-align:top; }
td.mono, .mono { font-family:"JetBrains Mono","IBM Plex Mono",Consolas,monospace; font-size:12px; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
tr.hit td { background:#f1f7ff; }
tr.hit td:first-child { box-shadow:inset 3px 0 0 var(--blue); }
.muted { color:var(--muted); }
pre.code { margin:0; background:var(--code); color:#d7e3f4; border-radius:10px; padding:14px 16px;
  font-family:"JetBrains Mono","IBM Plex Mono",Consolas,monospace; font-size:12px; line-height:1.6;
  white-space:pre-wrap; word-break:break-all; overflow:hidden; }
pre.code.ir { word-break:normal; overflow-wrap:anywhere; font-size:11.5px; }
table.tight td { padding:4px 10px; } table.tight .chip { padding:1px 8px; font-size:11.5px; }
pre.code .k { color:#7fb2ff; } pre.code .s { color:#9fe0b8; } pre.code .c { color:#8a96a5; }
.tabs { display:flex; gap:4px; flex-wrap:wrap; }
.tab { padding:6px 11px; border-radius:8px; font-size:12.5px; font-weight:700; color:#5f6b7a; border:1px solid transparent;
  cursor:pointer; }
.tab.on { background:var(--blue-soft); color:#15509f; border-color:var(--blue-line); }
.tab.off { color:#b4bcc8; text-decoration:line-through; }
.banner { display:flex; align-items:center; gap:14px; border-radius:12px; padding:14px 18px; }
.banner.ok { background:var(--ok-soft); border:1px solid #bfe5cf; }
.banner.no { background:#fdecea; border:1px solid #f5c6c2; }
.banner .big { font-size:20px; font-weight:800; }
.banner .why { color:#2c3644; font-size:14px; }
.check { display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px dashed #edf0f4; font-size:13px; }
.check:last-child { border-bottom:0; }
.ic { width:18px; height:18px; border-radius:50%; display:grid; place-items:center; color:#fff; font-size:11px;
  font-weight:800; flex:none; }
.ic.y { background:var(--ok); } .ic.x { background:var(--bad); } .ic.w { background:#c4ccd6; }
.ev { display:grid; grid-template-columns:1fr auto 1.1fr; gap:8px; align-items:center; padding:8px 10px;
  border:1px solid var(--line); border-radius:9px; margin-bottom:6px; font-size:13px; }
.ev .arrow { color:#a0aab8; }
.ev .src { justify-self:end; }
.log { font-size:12.5px; color:#3a4656; }
.log div { display:grid; grid-template-columns:70px 1fr auto; gap:8px; padding:6px 0; border-bottom:1px dashed #edf0f4; }
svg text { font-family:"Pretendard","Malgun Gothic",sans-serif; }
.legend { display:flex; gap:14px; color:var(--muted); font-size:12px; }
.switch { width:36px; height:20px; border-radius:999px; background:#cfd6e0; position:relative; display:inline-block; }
.switch::after { content:""; position:absolute; top:2px; left:2px; width:16px; height:16px; border-radius:50%;
  background:#fff; box-shadow:0 1px 2px rgba(0,0,0,.2); }
.switch.on { background:var(--blue); } .switch.on::after { left:18px; }
.kind { display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:700; padding:3px 9px;
  border-radius:999px; background:#fff; border:1px solid var(--line); white-space:nowrap; }
.kind i { width:8px; height:8px; border-radius:50%; display:inline-block; }
.layer { display:grid; grid-template-columns:92px 1fr; gap:10px; align-items:center; padding:9px 0;
  border-bottom:1px dashed #edf0f4; }
.layer:last-child { border-bottom:0; }
.layer .lbl { font-size:12px; font-weight:800; color:#3a4656; display:flex; align-items:center; gap:7px; }
.layer .lbl i { width:4px; height:22px; border-radius:2px; display:inline-block; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
"""

ICONS = {
    "space": '<path d="M3 6h6l2 2h10v11H3z"/>',
    "onto": '<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/>'
            '<path d="M7 7.5l3.6 8.3M17 7.5l-3.6 8.3M7.5 6h9"/>',
    "query": '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 4l-4 16"/>',
    "decide": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "check": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12l3 3 5-6"/>',
    "map": '<path d="M9 4l-6 3v13l6-3 6 3 6-3V4l-6 3z"/><path d="M9 4v13M15 7v13"/>',
    "library": '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="16" rx="1"/>'
               '<path d="M17 5.5l3.5-1 3 15-3.5 1z"/>',
}
NAV = [("space", "데이터 공간"), ("library", "온톨로지 라이브러리"), ("onto", "온톨로지"), ("query", "질의"), ("decide", "결정 · 액션"),
       ("check", "검증"), ("map", "데이터 지도")]


def _e(v: Any) -> str:
    return escape("" if v is None else str(v))


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:,.0f}" if v.is_integer() else f"{v:,.2f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return _e(v)


def _frame(screen_id: str, active: str, studio: Studio, body: str, counts: dict[str, int]) -> str:
    o = studio.onto
    nav = "".join(
        f'<a class="nav{" on" if k == active else ""}" href="#{k}"><svg viewBox="0 0 24 24">{ICONS[k]}</svg>{_e(label)}'
        f'{f"<span class=n>{counts[k]}</span>" if counts.get(k) else ""}</a>' for k, label in NAV)
    backends = "".join(f'<span class="chip"><span class="dot"></span>{_e(n)} · {_e(b.capabilities.language.upper())}'
                       f'</span>' for n, b in studio.backends.items())
    comp = studio.composition
    if comp:
        domains = [m.label or m.name for m in comp.modules if m.kind == "domain"]
        ident = (f'<span class="chip b">{_e(" · ".join(domains) or o.name)}</span>'
                 f'<span class="chip">모듈 {len(comp.modules)}개</span>')
    else:
        ident = f'<span class="chip b">{_e(o.label or o.name)}</span><span class="chip">판본 {_e(o.version)}</span>'
    return f"""<section class="screen" id="{screen_id}">
  <div class="top"><div class="brand"><div class="logo">X</div>XGEN 데이터 스튜디오</div>
    {ident}
    <div class="grow"></div>{backends}<div class="who"><div class="avatar">운영</div>운영자</div></div>
  <aside class="side"><h6>데이터 스튜디오</h6>{nav}
    <div class="foot"><b>정의는 한곳에, 값은 원천에</b>같은 정의가 원천 DB · 그래프 · 추론기에서 같은 답을 냅니다.</div></aside>
  <main class="main">{body}</main>
</section>"""


def _layers(studio: Studio) -> dict[str, int]:
    o = studio.onto
    out_edges: dict[str, set[str]] = defaultdict(set)
    for lk in o.links.values():
        if lk.source != lk.target:
            out_edges[lk.source].add(lk.target)
    for obj in o.objects.values():
        if obj.parent in o.objects:
            out_edges[obj.parent].add(obj.name)
    longest: dict[str, int] = defaultdict(int)
    for _ in range(len(o.objects)):
        for s, ts in out_edges.items():
            for t in ts:
                if longest[t] < longest[s] + 1 <= len(o.objects):
                    longest[t] = longest[s] + 1
    return {t: longest[t] for t in o.objects}


def _flow_svg(rows: list[list[tuple[str, str, str, bool]]], edges: list[tuple[str, str, str]], *, w: int = 860,
              row_gap: int = 104, bw: int = 168, bh: int = 50, row_labels: list[str] | None = None) -> str:
    """Rows of boxes (id, title, subtitle, highlighted) flowing top to bottom, joined by curved edges."""
    h = 30 + row_gap * (len(rows) - 1) + bh + 20
    left = 96 if row_labels else 20
    span = w - left - 20
    pos: dict[str, tuple[float, float]] = {}
    row_of: dict[str, int] = {}
    for r, items in enumerate(rows):
        gap = min(span / max(len(items), 1), bw + 64)
        x0 = left + (span - gap * len(items)) / 2 + (gap - bw) / 2
        for i, (nid, *_rest) in enumerate(items):
            pos[nid] = (x0 + i * gap, 30 + r * row_gap)
            row_of[nid] = r
    parts = ['<defs><marker id="am" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#9aa6b6"/></marker></defs>']
    for r, lbl in enumerate(row_labels or []):
        parts.append(f'<text x="12" y="{30 + r * row_gap + bh / 2 + 4}" font-size="12" font-weight="700" '
                     f'fill="#8a96a5">{_e(lbl)}</text>')
    labels = []
    for e in edges:
        src, dst, label = e[:3]
        dash = ' stroke-dasharray="5 4"' if len(e) > 3 and e[3] else ""
        if src not in pos or dst not in pos:
            continue
        sx, sy = pos[src]
        tx, ty = pos[dst]
        if src == dst:
            cx, cy = sx + bw, sy + bh / 2
            d = f"M{cx},{cy - 12} C{cx + 48},{cy - 42} {cx + 48},{cy + 42} {cx},{cy + 12}"
            lx, ly, anchor = cx + 44, cy + 4, "start"
        elif row_of[dst] - row_of[src] > 1 or row_of[dst] <= row_of[src]:
            side = -1 if sx + bw / 2 <= w / 2 else 1
            ex1 = sx if side < 0 else sx + bw
            ex2 = tx if side < 0 else tx + bw
            bend = side * (70 + 24 * abs(row_of[dst] - row_of[src]))
            d = f"M{ex1},{sy + bh / 2} C{ex1 + bend},{sy + bh / 2} {ex2 + bend},{ty + bh / 2} {ex2},{ty + bh / 2}"
            lx, ly, anchor = (ex1 + ex2) / 2 + bend * 0.75, (sy + ty) / 2 + bh / 2 + 4, "middle"
        else:
            x1, y1, x2, y2 = sx + bw / 2, sy + bh, tx + bw / 2, ty
            d = f"M{x1},{y1} C{x1},{(y1 + y2) / 2} {x2},{(y1 + y2) / 2} {x2},{y2 - 2}"
            lx, ly, anchor = (x1 + x2) / 2 + 8, (y1 + y2) / 2 + 4, "start"
        parts.append(f'<path d="{d}" fill="none" stroke="#9aa6b6" stroke-width="1.6" marker-end="url(#am)"{dash}/>')
        if label:
            labels.append(f'<text x="{lx}" y="{ly}" font-size="11.5" fill="#5f6b7a" text-anchor="{anchor}" '
                          f'paint-order="stroke" stroke="#fff" stroke-width="4">{_e(label)}</text>')
    for items in rows:
        for nid, title, sub, on, *rest in items:
            x, y = pos[nid]
            accent = rest[0] if rest else ""
            fill, stroke, tc, sc = (("#13213c", "#13213c", "#fff", "#b9c6dc") if on
                                    else ("#fff", accent or "#c9d2de", "#1b2330", "#8a96a5"))
            parts.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="11" fill="{fill}" stroke="{stroke}" '
                         f'stroke-width="{1.8 if accent and not on else 1.4}"/>')
            if accent:
                parts.append(f'<circle cx="{x + 13}" cy="{y + 13}" r="4" fill="{accent}"/>')
            parts.append(f'<text x="{x + bw / 2}" y="{y + (21 if sub else bh / 2 + 5)}" font-size="13.5" '
                         f'font-weight="800" fill="{tc}" text-anchor="middle">{_e(title)}</text>')
            if sub:
                parts.append(f'<text x="{x + bw / 2}" y="{y + 38}" font-size="11" fill="{sc}" text-anchor="middle">'
                             f'{_e(sub)}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="100%" preserveAspectRatio="xMidYMin meet" '
            f'role="img">{"".join(parts + labels)}</svg>')


def _module_kind(studio: Studio, element: str) -> str:
    comp = studio.composition
    if comp is None:
        return ""
    owner = comp.owner(element)
    return next((m.kind for m in comp.modules if m.name == owner), "")


def _schema_svg(studio: Studio, selected: str) -> str:
    o = studio.onto
    layers = _layers(studio)
    rows: list[list[tuple]] = [[] for _ in range(max(layers.values()) + 1)]
    for name, obj in o.objects.items():
        sub = f"{name} · {obj.table}" if obj.table else f"{name} · 상위 개념"
        accent = MODULE_COLOR.get(_module_kind(studio, f"object:{name}"), "")
        rows[layers[name]].append((name, obj.label or name, sub, name == selected, accent))
    edges: list[tuple] = [(lk.source, lk.target, lk.label or lk.name) for lk in o.links.values()]
    edges += [(obj.parent, obj.name, "하위 유형", True) for obj in o.objects.values() if obj.parent in o.objects]
    return _flow_svg(rows, edges, w=900, row_gap=88, bw=150, bh=46)


def _screen_ontology(studio: Studio, selected: str, counts) -> str:
    o = studio.onto
    obj = o.obj(selected)
    stats = [(len(o.objects), "객체"), (len(o.links), "관계"), (sum(len(x.properties) for x in o.objects.values()),
             "속성"), (len(o.decisions), "결정"), (len(o.actions), "액션"), (len(o.queries), "등록 질의")]
    stat_html = "".join(f'<div class="stat"><b>{n}</b><span>{_e(lbl)}</span></div>' for n, lbl in stats)
    def owner_chip(p) -> str:
        kind = _module_kind(studio, f"property:{obj.name}.{p.name}")
        if not kind:
            return ""
        name = studio.composition.owner(f"property:{obj.name}.{p.name}")
        return (f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;white-space:nowrap">'
                f'<i style="width:8px;height:8px;border-radius:50%;background:{MODULE_COLOR[kind]};display:inline-block">'
                f'</i>{_e(name)}</span>')

    rows = "".join(
        f'<tr><td><b>{_e(p.label or p.name)}</b><div class="muted mono">{_e(p.name)}</div></td>'
        f'<td><span class="chip{" b" if p.name == obj.key else ""}">{_e(p.type)}</span></td>'
        f'<td class="mono">{_e(p.col)}</td><td>{owner_chip(p)}</td></tr>' for p in obj.properties.values())
    if studio.composition:
        kinds = [m.kind for m in studio.composition.modules]
        legend = "".join(f'<span><i style="background:{MODULE_COLOR[k]}"></i>{MODULE_KIND[k]}</span>'
                         for k in dict.fromkeys(kinds) if k != "binding") + '<span>- - 하위 유형</span>'
    else:
        legend = ('<span><i style="background:#13213c"></i>선택</span><span><i style="background:#fff;'
                  'border:1px solid #c9d2de"></i>객체</span>')
    aligned = "".join(f'<span class="chip mono" style="font-size:11px">{_e(a.split("//", 1)[-1])}</span>'
                      for a in obj.aligned)
    if aligned:
        aligned = ('<div style="margin-top:14px"><div class="muted" style="font-size:12px;font-weight:700;'
                   f'margin-bottom:6px">표준 개념 정렬</div><div style="display:flex;gap:6px;flex-wrap:wrap">{aligned}</div></div>')
    if obj.parent:
        aligned = (f'<div style="margin-top:14px"><div class="muted" style="font-size:12px;font-weight:700;'
                   f'margin-bottom:6px">상위 개념</div><span class="chip n">{_e(studio.onto.obj(obj.parent).label)} · '
                   f'{_e(obj.parent)}</span></div>') + aligned
    states = ""
    if obj.states:
        states = " → ".join(f'<span class="chip{" n" if s == obj.states.initial else ""}">{_e(s)}</span>'
                            for s in obj.states.states)
        states = f'<div style="margin-top:14px"><div class="muted" style="font-size:12px;font-weight:700;margin-bottom:6px">' \
                 f'상태 전이 · {_e(obj.states.property)}</div><div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">' \
                 f'{states}</div></div>'
    links = [lk for lk in o.links.values() if selected in (lk.source, lk.target)]
    link_html = "".join(
        f'<span class="chip">{_e(lk.label or lk.name)} · {_e(o.obj(lk.target if lk.source == selected else lk.source).label)}'
        f'</span>' for lk in links)
    body = f"""
<div class="head"><div><h1>온톨로지</h1><div class="sub">업무 대상과 관계를 한 번 정의하고 원천 테이블에 바인딩합니다</div></div>
  <div class="right"><span class="btn ghost">OWL 내보내기</span><span class="btn ghost">SHACL</span>
  <span class="btn ghost">R2RML</span><span class="btn primary">변경 제안</span></div></div>
<div class="stats">{stat_html}</div>
<div class="grid" style="grid-template-columns:1.55fr 1fr">
  <div class="card"><div class="ch">스키마 그래프<div class="right legend">{legend}</div></div>
    <div class="cb" style="flex:1;padding:10px 12px">{_schema_svg(studio, selected)}</div></div>
  <div class="card"><div class="ch">{_e(obj.label)} <span class="muted mono" style="font-weight:600">{_e(obj.name)}</span>
    <div class="right"><span class="chip b">키 {_e(obj.key)}</span><span class="chip mono">{_e(obj.table)}</span></div></div>
    <div class="cb"><table><tr><th>속성</th><th>타입</th><th>원천 컬럼</th><th>모듈</th></tr>{rows}</table>{states}{aligned}
    <div style="margin-top:14px"><div class="muted" style="font-size:12px;font-weight:700;margin-bottom:6px">관계</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">{link_html}</div></div></div></div>
</div>"""
    return _frame("ontology", "onto", studio, body, counts)


def _screen_library(studio: Studio, counts) -> str:
    comp = studio.composition
    active = {m.name for m in comp.modules} if comp else set()
    if studio.library is not None:
        rows = studio.library.list()
    elif comp:
        rows = [{"name": m.name, "label": m.label, "kind": m.kind, "latest": m.version, "versions": [m.version],
                 "requires": [str(r) for r in m.requires], "counts": m.counts()} for m in comp.modules]
    else:
        o = studio.onto
        rows = [{"name": o.name, "label": o.label, "kind": "domain", "latest": o.version, "versions": [o.version],
                 "requires": [], "counts": {"objects": len(o.objects), "links": len(o.links),
                                            "decisions": len(o.decisions), "queries": len(o.queries)}}]
        active = {o.name}
    order = list(MODULE_KIND)
    rows.sort(key=lambda r: (order.index(r["kind"]), r["name"]))
    tabs = [f'<span class="tab on">전체 {len(rows)}</span>'] + [
        f'<span class="tab">{MODULE_KIND[k]} {n}</span>' for k in order
        if (n := sum(r["kind"] == k for r in rows))]
    body_rows = []
    for r in rows:
        c = r["counts"]
        parts = [f"객체 {c.get('objects', 0)}", f"관계 {c.get('links', 0)}", f"결정 {c.get('decisions', 0)}",
                 f"질의 {c.get('queries', 0)}", f"확장 {c.get('extends', 0)}"]
        made = " · ".join(x for x in parts if not x.endswith(" 0")) or "-"
        req = " ".join(f'<span class="chip mono" style="font-size:11px">{_e(x)}</span>' for x in r["requires"]) or \
            '<span class="muted">-</span>'
        kind = r["kind"]
        body_rows.append(
            f'<tr><td><b>{_e(r["label"] or r["name"])}</b><div class="muted mono">{_e(r["name"])}</div></td>'
            f'<td><span class="kind"><i style="background:{MODULE_COLOR[kind]}"></i>{MODULE_KIND[kind]}</span></td>'
            f'<td class="mono" style="white-space:nowrap">{_e(r["latest"])}</td>'
            f'<td>{req}</td><td class="muted" style="font-size:12.5px">{_e(made)}</td>'
            f'<td style="text-align:center"><span class="switch{" on" if r["name"] in active else ""}"></span></td></tr>')
    layers = ""
    if comp:
        for k in order:
            ms = [m for m in comp.modules if m.kind == k]
            if not ms:
                continue
            chips = " ".join(f'<span class="chip">{_e(m.label or m.name)} <span class="muted mono">{_e(m.version)}</span>'
                             f'</span>' for m in ms)
            layers += (f'<div class="layer"><div class="lbl"><i style="background:{MODULE_COLOR[k]}"></i>{MODULE_KIND[k]}'
                       f'</div><div style="display:flex;gap:6px;flex-wrap:wrap">{chips}</div></div>')
    impacts = ""
    if comp:
        picks = [m.name for m in comp.modules if m.kind == "industry"][:1] + \
                [m.name for m in comp.modules if m.kind == "domain"][:1]
        for name in picks:
            imp = studio.detach_impact(name)
            label = next(m.label for m in comp.modules if m.name == name)
            if imp.ok:
                items = "".join(f'<span class="chip mono" style="font-size:11px">{_e(e)}</span>' for e in imp.removed[:6])
                impacts += (f'<div style="padding:10px 0;border-bottom:1px dashed #edf0f4"><div style="display:flex;'
                            f'align-items:center;gap:8px;margin-bottom:6px"><b>{_e(label)}</b><span class="chip ok">'
                            f'뺄 수 있음</span><span class="muted" style="margin-left:auto;font-size:12px">'
                            f'{len(imp.removed)}개 항목이 빠집니다</span></div><div style="display:flex;gap:5px;'
                            f'flex-wrap:wrap">{items}</div></div>')
            else:
                deps = ", ".join(imp.dependents)
                impacts += (f'<div style="padding:10px 0"><div style="display:flex;align-items:center;gap:8px;'
                            f'margin-bottom:6px"><b>{_e(label)}</b><span class="chip warn">함께 빼야 함</span></div>'
                            f'<div class="muted" style="font-size:12.5px">기대고 있는 모듈 {len(imp.dependents)}개: '
                            f'{_e(deps)}</div></div>')
    body = f"""
<div class="head"><div><h1>온톨로지 라이브러리</h1><div class="sub">도메인 온톨로지를 따로 만들고 판본을 관리하며, 스튜디오에 꽂고 뺍니다</div></div>
  <div class="right"><span class="btn ghost">OWL 가져오기</span><span class="btn ghost">판본 비교</span><span class="btn primary">새 온톨로지</span></div></div>
<div class="tabs">{"".join(tabs)}</div>
<div class="grid" style="grid-template-columns:1.62fr 1fr">
  <div class="card"><div class="ch">모듈<div class="right muted" style="font-weight:600;font-size:12px">스튜디오에 꽂힌 것 {len(active)}개</div></div>
    <div class="cb" style="padding:0"><table><tr><th>온톨로지</th><th>종류</th><th>판본</th><th>요구</th><th>구성</th><th style="text-align:center">스튜디오</th></tr>
    {"".join(body_rows)}</table></div></div>
  <div style="display:flex;flex-direction:column;gap:16px;min-height:0">
    <div class="card"><div class="ch">지금 꽂힌 구성<div class="right muted" style="font-weight:600;font-size:12px">아래 층이 위 층에 기댑니다</div></div>
      <div class="cb">{layers}</div></div>
    <div class="card" style="flex:1"><div class="ch">빼기 전 영향</div><div class="cb">{impacts}</div></div></div>
</div>"""
    return _frame("library", "library", studio, body, counts)


def _highlight(code: str, language: str) -> str:
    words = {"SELECT", "FROM", "WHERE", "JOIN", "LEFT", "ON", "GROUP", "BY", "ORDER", "LIMIT", "AS", "AND", "OR",
             "NOT", "EXISTS", "MATCH", "OPTIONAL", "RETURN", "WITH", "DISTINCT", "ASC", "DESC", "NULLS", "LAST",
             "FILTER", "IN", "IS", "NULL", "GRAPH_TABLE", "COLUMNS", "FETCH", "FIRST", "ROWS", "ONLY", "RECURSIVE",
             "UNION", "ALL", "COUNT", "SUM", "CASE", "WHEN", "THEN", "ELSE", "END", "ANY", "GRAPH"}
    out = []
    for line in code.split("\n"):
        tokens = []
        for tok in line.replace("\t", "  ").split(" "):
            plain = tok.strip("(),")
            if plain.upper() in words and plain.isalpha() or plain.upper() in ("GRAPH_TABLE",):
                tokens.append(_e(tok).replace(_e(plain), f'<span class="k">{_e(plain)}</span>', 1))
            elif tok.startswith(("'", '"')) and language.startswith("sparql") and tok.endswith(('"', "'")):
                tokens.append(f'<span class="s">{_e(tok)}</span>')
            else:
                tokens.append(_e(tok))
        out.append(" ".join(tokens))
    return "\n".join(out)


def _ir_text(d: dict) -> str:
    """IR JSON with one key per line and one list item per line."""
    def one(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False)

    lines = ["{"]
    items = list(d.items())
    for i, (k, v) in enumerate(items):
        end = "," if i < len(items) - 1 else ""
        if isinstance(v, list) and len(v) > 1:
            lines.append(f'  "{k}": [')
            lines += [f"    {one(x)}{',' if j < len(v) - 1 else ''}" for j, x in enumerate(v)]
            lines.append(f"  ]{end}")
        else:
            lines.append(f'  "{k}": {one(v)}{end}')
    return "\n".join(lines + ["}"])


def _screen_query(studio: Studio, name: str, active: str, counts) -> str:
    rq = studio.onto.queries[name]
    q = studio.query(name)
    params = studio.registered().get(name, (q, {}))[1]
    tabs, code, langs = [], "", []
    for target, label in TARGETS:
        try:
            c = studio.translate(name, target)
            if target == active:
                code = c.preview(params) if c.style != "inline" else c.bind(params)[0]
            tabs.append(f'<span class="tab{" on" if target == active else ""}">{_e(label)}</span>')
            langs.append(f'<tr><td><b>{_e(label)}</b></td><td><span class="chip ok">변환됨</span></td>'
                         f'<td class="num">{c.text.count(chr(10)) + 1}줄</td><td class="num">{len(c.params)}개</td></tr>')
        except CompileError as e:
            tabs.append(f'<span class="tab off" title="{_e(e)}">{_e(label)}</span>')
            langs.append(f'<tr><td><b>{_e(label)}</b></td><td><span class="chip warn">지원 안 함</span></td>'
                         f'<td colspan="2" class="muted">{_e(e)}</td></tr>')
    results = []
    first = None
    agree = True
    for bname, b in studio.backends.items():
        try:
            res = studio.run(name, params, backend=bname)
        except Exception as e:
            results.append(f'<div class="card"><div class="ch">{_e(bname)}</div><div class="cb muted">{_e(e)}</div></div>')
            continue
        norm = normalize_rows(res.rows, res.columns, res.compiled.column_types)
        if first is None:
            first = norm
        elif sorted(map(repr, norm)) != sorted(map(repr, first)):
            agree = False
        head = "".join(f"<th>{_e(c)}</th>" for c in res.columns)
        body = "".join("<tr>" + "".join(f'<td class="{"num" if isinstance(v, (int, float)) else ""}">{_fmt(v)}</td>'
                                        for v in r) + "</tr>" for r in norm[:6])
        lang = b.capabilities.language.upper()
        results.append(f'<div class="card"><div class="ch">{_e(bname)}<span class="chip">{_e(lang)} · '
                       f'{_e(b.capabilities.dialect)}</span><div class="right"><span class="chip">{len(norm)}행</span>'
                       f'</div></div><div class="cb" style="padding:0"><table><tr>{head}</tr>{body}</table></div></div>')
    ir = _ir_text(q.to_dict())
    verdict = ('<span class="chip ok">✓ 모든 백엔드 같은 결과</span>' if agree and len(results) > 1
               else '<span class="chip warn">결과 차이</span>' if len(results) > 1 else "")
    label = dict(TARGETS)[active]
    body = f"""
<div class="head"><div><h1>{_e(rq.label or name)} <span class="muted mono" style="font-size:15px">{_e(name)}</span></h1>
  <div class="sub">질문은 온톨로지 질의로 한 번 쓰고, 백엔드마다 맞는 쿼리문으로 바꿔 실행합니다</div></div>
  <div class="right">{verdict}<span class="btn primary">실행</span></div></div>
<div class="grid" style="grid-template-columns:380px 1fr;flex:none;height:520px">
  <div class="card"><div class="ch">온톨로지 질의 IR<div class="right"><span class="chip b">검사 통과</span></div></div>
    <div class="cb"><pre class="code ir" style="height:452px">{_e(ir)}</pre></div></div>
  <div class="card"><div class="ch">백엔드 쿼리문<div class="right tabs">{"".join(tabs)}</div></div>
    <div class="cb"><pre class="code" style="height:128px">{_highlight(code, active)}</pre>
    <div class="muted" style="font-size:12px;margin:6px 0 10px">{_e(label)} · 값은 모두 파라미터로 넘깁니다 (미리 보기에만 채워 보임)</div>
    <table class="tight"><tr><th>언어</th><th>상태</th><th style="text-align:right">쿼리문</th><th style="text-align:right">파라미터</th></tr>{"".join(langs)}</table></div></div>
</div>
<div class="grid" style="grid-template-columns:repeat({max(len(results), 1)},1fr)">{"".join(results)}</div>"""
    return _frame("query", "query", studio, body, counts)


def _screen_decision(studio: Studio, name: str, key: str, counts) -> str:
    table = studio.onto.decisions[name]
    res = studio.decide(name, key)
    outs = res.outputs if isinstance(res.outputs, dict) else {}
    ok = bool(outs.get(next(iter(table.outputs), ""), False))
    reason = next((v for k, v in outs.items() if isinstance(v, str)), "")
    inputs = list(table.inputs)
    def th(name: str) -> str:
        return f"<th>{_e(name).replace('_', '_<wbr>')}</th>"

    head = "<th>규칙</th>" + "".join(th(i) for i in inputs) + "".join(th(o) for o in table.outputs)
    rows = ""
    clip = "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px"
    for r in table.rules:
        cells = "".join(f'<td class="mono" style="white-space:nowrap">{_e(r.when.get(i, "-"))}</td>' for i in inputs)
        outc = "".join(f'<td style="{clip}">{_fmt(r.then.get(o))}</td>' for o in table.outputs)
        cite = f'<div class="muted" style="font-size:10.5px;font-family:inherit">{_e(r.cite)}</div>' if r.cite else ""
        rows += (f'<tr class="{"hit" if r.id in res.matched else ""}"><td class="mono" style="white-space:nowrap">'
                 f'{_e(r.id)}{cite}</td>{cells}{outc}</tr>')
    ev = "".join(f'<div class="ev"><div><b>{_e(e.input)}</b><div class="muted mono">{_e(e.object_type)} {_e(e.key)}</div>'
                 f'</div><div><span class="chip b">{_fmt(e.value)}</span></div><div class="src mono muted">← {_e(e.source)}'
                 f'</div></div>' for e in res.evidence)
    action = next((a for a in studio.onto.actions.values()
                   if any(c.decision == name for c in a.criteria)), None)
    action_html = ""
    if action:
        role = next((r.name for r in studio.onto.roles.values() if r.can("request", action.name) and r.row_filters),
                    next(iter(studio.onto.roles), ""))
        p = studio.actions.request(action.name, key, {k: "사이즈가 맞지 않음" for k in action.parameters},
                                   actor=Actor("agent:고객응대", "agent", [role]))
        names = {"role": "역할 권한", "parameters": "파라미터", "target": "대상 확인", "state": "상태 전이"}
        first_out = next(iter(table.outputs), "")
        detail = {"role": (studio.onto.roles[role].label or role) if role else "",
                  "parameters": ", ".join(action.parameters) or "없음",
                  "target": f"{studio.onto.obj(action.target).label} {key}"}
        rows_ = []
        for c in p.checks:
            title = names.get(c.name) or (f"결정 · {table.label}" if c.name.startswith("decision:") else c.name)
            text = detail.get(c.name) or (f"{first_out} = {_fmt(outs.get(first_out))}"
                                          if c.name.startswith("decision:") else c.detail)
            mark = '<span class="ic y">✓</span>' if c.passed else '<span class="ic x">!</span>'
            rows_.append(f'<div class="check">{mark}<b style="min-width:122px">{_e(title)}</b>'
                         f'<span class="muted">{_e(text)}</span></div>')
        checks = "".join(rows_)
        status = {"pending": ('warn', "승인 대기"), "rejected": ("", "반려"), "executed": ("ok", "실행됨")}[p.status]
        log = "".join(f'<div><span class="muted">{_e(a.event)}</span><span>{_e(a.actor)}</span>'
                      f'<span class="muted mono">{_e(a.proposal)}</span></div>' for a in studio.actions.audit[-3:])
        action_html = f"""<div class="card" style="flex:1"><div class="ch">{_e(action.label or action.name)}
  <span class="muted mono" style="font-weight:600">{_e(action.name)}</span><div class="right">
  <span class="chip {status[0]}">{status[1]}</span></div></div><div class="cb">
  <div class="muted" style="font-size:12.5px;margin-bottom:8px">에이전트가 요청했습니다. 검사를 모두 통과하면 사람이 승인한 뒤에만 원천에 씁니다.</div>
  {checks}<div style="display:flex;gap:8px;margin:12px 0 10px"><span class="btn primary" style="flex:1;text-align:center">승인하고 실행</span>
  <span class="btn" style="flex:1;text-align:center">반려</span></div>
  <div class="muted" style="font-size:12px;font-weight:700;margin-bottom:2px">감사 기록</div><div class="log">{log}</div></div></div>"""
    banner_cls = "ok" if ok else "no"
    verdict = "가능" if ok else "불가"
    body = f"""
<div class="head"><div><h1>{_e(table.label or name)} <span class="muted mono" style="font-size:15px">{_e(name)}</span></h1>
  <div class="sub">{_e(studio.onto.obj(table.target).label)} {_e(key)} · 결정표로 판정하고 근거가 된 원천 값을 함께 돌려줍니다</div></div>
  <div class="right"><span class="chip">엔진 {_e(res.engine)}</span><span class="chip">ZEN JDM 내보내기</span></div></div>
<div class="banner {banner_cls}"><span class="ic {"y" if ok else "x"}" style="width:30px;height:30px;font-size:16px">{"✓" if ok else "!"}</span>
  <div><div class="big">{_e(table.label)} · {verdict}</div><div class="why">{_e(reason)}</div></div>
  <div style="margin-left:auto"><span class="chip b">규칙 {_e(", ".join(res.matched))}</span></div></div>
<div class="grid" style="grid-template-columns:minmax(0,1.5fr) minmax(420px,1fr)">
  <div style="display:flex;flex-direction:column;gap:16px;min-height:0">
    <div class="card"><div class="ch">결정표<div class="right"><span class="chip">적중 정책 {_e(table.hit_policy)}</span></div></div>
      <div class="cb" style="padding:0"><table class="tight" style="font-size:12.5px"><tr>{head}</tr>{rows}</table></div></div>
    <div class="card"><div class="ch">근거 경로</div><div class="cb">{ev}</div></div></div>
  {action_html}
</div>"""
    return _frame("decision", "decide", studio, body, counts)


def _screen_map(studio: Studio, counts) -> str:
    cat = from_ontology(studio.onto, database=studio.source or "source")
    agent_role = next((r.name for r in studio.onto.roles.values() if r.row_filters), next(iter(studio.onto.roles), ""))
    if studio.onto.decisions:
        dec = next(iter(studio.onto.decisions))
        cat.add_folder("정책서")
        cat.add_file("정책서/반품정책.pdf", folder="정책서", collection="커머스 정책")
        cat.add_file("정책서/옛 공지.pdf", folder="정책서")
        cat.add_agent("고객응대", roles=[agent_role], uses=["collection:커머스 정책", f"decision:{dec}"])
    start = None
    if studio.onto.decisions:
        res = studio.decide(next(iter(studio.onto.decisions)), next(
            (q.key for q in studio.onto.questions if q.decision), ""))
        start = next((f"column:{e.source}" for e in res.evidence if "." in e.source), None)
    start = start or next(a.id for a in cat.assets.values() if a.kind == "column")
    impacted = cat.impact(start)
    groups = [("column", ["column"]), ("property", ["property"]), ("query", ["query", "decision"]),
              ("action", ["action"]), ("role", ["role"]), ("agent", ["agent"])]
    found: dict[str, list] = defaultdict(list)
    found["column"].append(cat.assets[start])
    for a in impacted:
        found[a.kind].append(a)
    rows, row_labels = [], []
    for _, kinds in groups:
        items = [a for k in kinds for a in found.get(k, [])]
        if not items:
            continue
        row_labels.append(" · ".join(KIND_LABEL[k] for k in kinds if found.get(k)))
        row = []
        for a in items:
            if a.kind == "property":
                owner, prop = a.id.split(":", 1)[1].split(".", 1)
                title, sub = a.label, f"{owner}.{prop}"
            elif a.kind == "column":
                title, sub = a.label, "원천 컬럼"
            else:
                title, sub = a.label, a.id.split(":", 1)[1]
            row.append((a.id, title, sub, a.id == start))
        rows.append(row)
    ids = {nid for r in rows for nid, *_ in r}
    edges = [(r.target, r.source, "") for r in cat.relations
             if r.source in ids and r.target in ids and r.kind in ("uses", "mapsTo", "hasRole")]
    svg = _flow_svg(rows, edges, w=900, row_gap=94, bw=196, bh=48, row_labels=row_labels)
    order = ["column", "property", "query", "decision", "action", "role", "agent"]
    sees = cat.sees("고객응대") if "agent:고객응대" in cat.assets else []
    by_kind = defaultdict(int)
    for a in sees:
        by_kind[a.kind] += 1
    see_html = "".join(f'<div class="stat"><b>{n}</b><span>{_e(KIND_LABEL.get(k, k))}</span></div>'
                       for k, n in sorted(by_kind.items(), key=lambda x: order.index(x[0]) if x[0] in order else 99)
                       if k in ("table", "column", "object", "file", "collection", "decision"))
    unused = "".join(f'<tr><td><span class="chip">{_e(KIND_LABEL.get(a.kind, a.kind))}</span></td>'
                     f'<td class="mono">{_e(a.label)}</td></tr>' for a in cat.unused()[:8])
    body = f"""
<div class="head"><div><h1>데이터 지도</h1><div class="sub">AI 가 쓸 수 있는 데이터 공간 자체를 그래프로 봅니다 · 자산 {len(cat.assets)} · 연결 {len(cat.relations)}</div></div>
  <div class="right"><span class="chip">에이전트가 보는 것</span><span class="chip b">영향 범위</span><span class="chip">쓰지 않는 데이터</span></div></div>
<div class="grid" style="grid-template-columns:1.7fr 1fr">
  <div class="card"><div class="ch">영향 범위 · <span class="mono" style="font-weight:600">{_e(cat.assets[start].label)}</span>
    <div class="right"><span class="chip warn">이 컬럼이 바뀌면 {len(impacted)}곳이 영향을 받습니다</span></div></div>
    <div class="cb" style="flex:1;padding:10px 14px">{svg}</div></div>
  <div style="display:flex;flex-direction:column;gap:16px;min-height:0">
    <div class="card"><div class="ch">고객응대 에이전트가 보는 것</div><div class="cb">
      <div class="stats" style="grid-template-columns:repeat(3,1fr)">{see_html}</div></div></div>
    <div class="card" style="flex:1"><div class="ch">아무도 쓰지 않는 데이터</div><div class="cb" style="padding:0">
      <table><tr><th>종류</th><th>자산</th></tr>{unused}</table></div></div></div>
</div>"""
    return _frame("map", "map", studio, body, counts)


def render(studio: Studio, *, query: str = "", decision: str = "", key: str = "", selected: str = "",
           target: str = "cypher") -> str:
    """Build the studio page; each screen is a 1440x900 section (#ontology, #query, #decision, #map)."""
    o = studio.onto
    query = query or next(iter(o.queries), "")
    decision = decision or next(iter(o.decisions), "")
    key = key or next((q.key for q in o.questions if q.decision == decision), "")
    selected = selected or (o.decisions[decision].target if decision else next(iter(o.objects)))
    counts = {"onto": len(o.objects), "query": len(o.queries), "decide": len(o.decisions) + len(o.actions),
              "check": len(o.questions),
              "library": len(studio.library.names()) if studio.library is not None else
              (len(studio.composition.modules) if studio.composition else 1)}
    screens = [_screen_library(studio, counts), _screen_ontology(studio, selected, counts)]
    if query:
        screens.append(_screen_query(studio, query, target, counts))
    if decision and key:
        screens.append(_screen_decision(studio, decision, key, counts))
    screens.append(_screen_map(studio, counts))
    script = ("<script>const ids=['library','ontology','query','decision','map'];function show(){"
              "const h=location.hash.slice(1);"
              "const m={onto:'ontology',query:'query',decide:'decision',map:'map',library:'library'};const id=m[h]||h;"
              "if(!document.body.classList.contains('single'))return;document.querySelectorAll('.screen').forEach("
              "s=>s.classList.toggle('on',s.id===(ids.includes(id)?id:'ontology')));}"
              "addEventListener('hashchange',show);show();</script>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>XGEN 데이터 스튜디오</title>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<link rel='stylesheet' href='https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/"
            f"pretendard.min.css'><style>{CSS}</style></head><body>{''.join(screens)}{script}</body></html>")
