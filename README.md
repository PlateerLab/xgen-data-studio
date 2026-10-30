# xgen-data-studio

**도메인 온톨로지는 한 벌로 정의하고, 실행은 고객사가 쓰는 어느 저장소 · 추론기에서나.**
XGEN 데이터 스튜디오의 실행 어댑터입니다. 객체 · 속성 · 관계 · 상태 · 결정 · 액션 · 권한을 한 번 정의하고 원천 테이블에 바인딩하면,
같은 질의가 SQL · Cypher · GQL · SPARQL · SQL/PGQ 로 바뀌어 각 백엔드에서 실행됩니다. 들어오는 SPARQL · Cypher 도 받아 다른 백엔드에서 돌립니다.

```
 정의 정본 (YAML/JSON → PostgreSQL)        실행 어댑터 (이 패키지)                              고객사 백엔드
┌────────────────────────────┐   ┌───────────────────────────────────────────────┐   ┌─────────────────────────┐
│ 객체 · 속성 · 관계 · 인터페이스│   │ LLM 보조: 자연어 → 질의 IR (검사 → 고쳐 다시)    │   │ 관계형 DB (원천)          │
│ 상태 전이 · 결정표 · 액션    │──▶│ 온톨로지 질의 IR ← 들어오는 SPARQL · Cypher      │──▶│ RDF 트리플스토어          │
│ 역할(행 필터) · 검증 질문    │   │ 컴파일러: SQL(+방언) │ Cypher │ GQL │ SPARQL │ PGQ │   │ 속성 그래프              │
│ 바인딩: 테이블 · 키 · 컬럼   │   │ 포트: 저장소(투영·변경분) │ 추론·검증 │ 판정      │   │ GQL · SQL/PGQ 엔진       │
│ 내보내기 OWL·SHACL·R2RML    │   │ 적합성 시험: 같은 질의, 백엔드마다 같은 결과      │   │ 추론기 · 결정 엔진        │
└────────────────────────────┘   └───────────────────────────────────────────────┘   └─────────────────────────┘
                                   에이전트 면(MCP): 스키마 설명 · 질의 · 결정 · 선언된 액션 요청(사람이 승인)
```

## 설치

```bash
pip install "xgen-data-studio[all]"        # rdflib · sqlglot · pySHACL · owlrl · ZEN · MCP · YAML
pip install xgen-data-studio               # 핵심만: 외부 의존성 없음 (SQLite · JSON · 결정표 · 규칙)
```

선택 묶음: `yaml` `rdf` `sql` `shacl` `owl` `zen` `postgres` `neo4j` `mcp`.

## 빠른 시작

```python
from xgen_data_studio import Ontology
from xgen_data_studio.studio import Studio
from xgen_data_studio.backends.sql import SqliteBackend
from xgen_data_studio.backends.rdf import RdflibBackend

onto = Ontology.load("examples/commerce/ontology.yaml").check()
studio = Studio(onto)
studio.add_backend("source", SqliteBackend("commerce.db"))     # 원천: 값은 여기서 읽습니다
studio.add_backend("graph", RdflibBackend())                   # 그래프: 필요할 때만 투영합니다
studio.project()                                               # 다음 호출부터는 변경분만 반영

studio.run("lowStock", {"threshold": 5})                       # 등록 질의 → SQL
studio.run("lowStock", {"threshold": 5}, backend="graph")      # 같은 질의 → SPARQL
studio.translate("lowStock", "sql:oracle").text                # 방언만 보기
studio.run_cypher("MATCH (o:Order)-[:hasItem]->(i:OrderItem) RETURN o.order_id, count(i) AS n")
studio.decide("returnEligibility", "I1001").outputs            # {'eligible': True, 'reason': ...} + 근거
studio.conformance().summary()                                 # 백엔드끼리 결과 대조
studio.questions().accuracy                                    # 검증 질문 정답률
```

명령줄은 `xds` 입니다.

```bash
xds validate examples/commerce/ontology.yaml
xds translate examples/commerce/ontology.yaml lowStock --to sql:mysql --param threshold=5
xds translate examples/commerce/ontology.yaml "MATCH (o:Order) RETURN o.status, count(o) AS n" --from cypher --to sparql
xds export examples/commerce/ontology.yaml --format owl      # shacl · r2rml · pgq · jdm · json · yaml · report
xds questions examples/commerce/studio.yaml
xds conformance examples/commerce/studio.yaml
xds mcp examples/commerce/studio.yaml --role customer_agent --principal customer_id=C001
```

## 정의 형식

예시 전체는 [`examples/commerce/ontology.yaml`](examples/commerce/ontology.yaml) 입니다.

| 항목 | 쓰는 법 | 쓰임 |
|---|---|---|
| `objects` | `key`, `source.table`, `properties`(type · label · column · values · required), `parent`, `implements`, `states` | 객체와 원천 테이블 바인딩. 속성 이름은 IRI 하나로 쓰이므로 타입이 같아야 합니다 |
| `links` | `from` · `to` · `cardinality`, `on: {원천속성: 대상속성}` 또는 `via: {table, source, target}`, `inverse`, `transitive`, `symmetric`, `required` | 관계와 조인 바인딩 |
| `interfaces` | 공통 속성 목록 | 여러 객체가 같은 모양을 가짐 |
| `decisions` | `target`, `inputs`(`property` · `path`+`property` · `days_since` · `count` · `param`), `outputs`, `rules`(`when` 셀 · `then`), `hit_policy` | 업무 판정. 결과와 함께 어느 테이블 · 컬럼 값으로 판정했는지 근거를 돌려줍니다 |
| `actions` | `target`, `parameters`, `criteria`(결정 기대값 · 상태), `set`, `transition_to`, `approval` | 요청 → 검사 → 사람 승인 → 원천 반영 → 감사 기록 |
| `roles` | `read`, `row_filters`(`$self` · `{principal: 속성}`), `run`, `request`, `execute` | 에이전트가 볼 수 있는 행과 할 수 있는 일 |
| `queries` | 이름 붙은 질의 IR + `params` + `example` | 등록 질의. LLM 은 이름과 파라미터만 고르면 됩니다 |
| `questions` | 질의 또는 결정 + 기대값(`rows` · `column/values` · `first` · 결정 출력) | 검증 질문과 정답률 |

결정표 셀: `-`(아무거나) · `null` · `not null` · `<= 7` · `[1..7]` · `"VIP"` · `!= "NORMAL"` · `in ["A", "B"]` · `true`.

## 질의 IR

```json
{"match": {"o": "Order", "i": "OrderItem"},
 "edges": [["o", "hasItem", "i"], {"from": "k", "link": "broader", "to": "a", "hops": [1, 3]}],
 "where": {"and": [{"ne": ["o.status", "CANCELLED"]},
                   {"not_exists": {"match": {"c": "Claim"}, "edges": [["i", "hasClaim", "c"]]}}]},
 "return": [{"col": "o.order_id", "as": "order"}, {"sum": "i.unit_price", "as": "total"}],
 "order": ["-total"], "limit": 10}
```

비교 `eq ne lt lte gt gte` · `in` `not_in` · `contains` · `is_null` `not_null` · `and or not` · `exists` `not_exists`.
집계 `count count_distinct sum avg min max`. 역관계 이름(`itemOf`)으로 써도 방향을 알아서 맞춥니다. 값은 모두 파라미터로 넘기며 쿼리문에 끼워 넣지 않습니다.
정렬은 모든 백엔드에서 NULL 이 뒤로 갑니다.

## 백엔드

| 언어 | 백엔드 (예) | optional | exists | 다단계 홉 | contains | 비고 |
|---|---|---|---|---|---|---|
| SQL | PostgreSQL · SQLite 직접, 그 밖은 sqlglot(MySQL · Oracle · SQL Server · Snowflake · BigQuery …) | LEFT JOIN | EXISTS | 재귀 CTE | strpos · instr | `SqliteBackend`, `DbApiBackend`(qmark · format · numeric) |
| Cypher 25 | Neo4j · Memgraph · Neptune openCypher · Apache AGE | OPTIONAL MATCH | EXISTS {} | `*1..3` + WITH DISTINCT | CONTAINS | `Neo4jBackend`, 투영은 UNWIND · MERGE |
| GQL | Spanner Graph · BigQuery Graph · Fabric Graph | OPTIONAL MATCH | EXISTS {} | `{1,3}` + ANY | 없음(오류로 알림) | `CallableBackend` 로 드라이버를 감쌉니다 |
| SPARQL 1.1 | rdflib · Fuseki · GraphDB · Stardog · Virtuoso · Oxigraph | OPTIONAL | FILTER EXISTS | 경로 대안 + DISTINCT | CONTAINS | `RdflibBackend`, `SparqlEndpointBackend`(GSP · Update) |
| SQL/PGQ | Oracle 26ai · Spanner | 없음 | 없음 | `{1,3}` | POSITION | `graph_ddl()` 이 CREATE PROPERTY GRAPH 를 만듭니다 |

할 수 있는 일은 `Capabilities` 로 선언하고, 쓰지 못하는 기능을 쓰는 질의는 실행 전에 알립니다.
그래프 백엔드는 원천을 읽어 투영(`project`)하고, 다음부터는 이전 투영과의 변경분(SPARQL `DELETE/INSERT DATA`, Cypher `MERGE/DELETE`)만 보냅니다.

## 추론 · 검증 · 교환

| 기능 | 함수 | 하는 일 |
|---|---|---|
| 규칙 | `reason.rules.run_rules` | 역관계 · 대칭 · 전이(깊이 상한) 유도, 근거 경로 기록. 필수 관계 · 카디널리티 · 배타 · 필수 속성 · 열거값 · 상태 검사 |
| SHACL | `reason.shacl.to_shacl` / `validate` | 정의에서 형상 생성, pySHACL 로 투영 검증 |
| OWL RL | `reason.owl_rl.materialize` | owlrl 물질화. 규칙 엔진과 같은 사실을 내는지 시험합니다 |
| OWL | `exchange.owl.to_owl` | 클래스 · 데이터/객체 속성 · 역관계 · 전이. 담지 못하는 것은 보존 / 조정 / 미지원 리포트 |
| R2RML | `exchange.r2rml.to_r2rml` | 바인딩을 R2RML 로. Ontop · Stardog · GraphDB 가 원천 위에서 SPARQL 을 바로 답합니다 |
| 가져오기 | `exchange.importer.from_owl` | FIBO · schema.org · GS1 같은 OWL/RDFS 를 정의 초안으로, 리포트와 함께 |
| 결정 엔진 | `decide.zen.to_jdm` / `evaluate_zen` | 결정표를 GoRules JDM 으로 내보내 ZEN 에서 실행. 내장 엔진과 결과를 대조합니다 |

## 자산 온톨로지

`catalog.from_ontology(onto)` 가 DB · 테이블 · 컬럼 · 객체 · 속성 · 관계 · 질의 · 결정 · 액션 · 역할을 그래프로 잇고,
`add_folder` · `add_file` · `add_agent` 로 폴더 · 파일 · 컬렉션 · 에이전트를 더합니다.

- `sees("고객응대")`: 그 에이전트가 역할과 도구로 닿는 테이블 · 컬럼 · 파일
- `impact("column:order_items.delivered_at")`: 그 컬럼이 바뀌면 영향을 받는 속성 · 질의 · 결정 · 액션 · 역할 · 에이전트
- `unused()`: 어느 에이전트도 쓰지 않는 테이블 · 컬럼 · 파일

## LLM 보조

`nl.IRGenerator(onto, llm)` 은 스키마 카드(역할이 읽을 수 있는 것만)와 IR 형식을 주고 질의 IR 이나 등록 질의 이름을 받습니다.
IR 은 온톨로지로 검사하고, 걸리면 문제 목록을 붙여 다시 묻습니다. LLM 은 백엔드 쿼리문을 직접 쓰지 않습니다. `llm` 은 `(system, prompt) -> str` 인 함수면 무엇이든 됩니다.

## MCP

```bash
xds mcp studio.yaml --role customer_agent --principal customer_id=C001 [--read-only]
```

도구: `describe_ontology` · `list_backends` · `translate_query` · `run_query` · `run_sparql` · `run_cypher` · `decide` · `request_action` · `list_proposals`.
모든 호출은 역할의 행 필터 안에서 돕니다. 액션은 요청만 만들고, 원천에 쓰는 것은 사람이 `approve` 한 뒤입니다.

## 설정 파일

```yaml
ontology: ontology.yaml
backends:
  source: {kind: sqlite, path: commerce.db, source: true}       # postgres(dsn) · dbapi(module, connect)
  graph:  {kind: rdflib}                                         # sparql(query_url, update_url, gsp_url)
  neo:    {kind: neo4j, uri: "bolt://host:7687", password: "${NEO4J_PASSWORD}"}
project: [graph]
```

## 개발

```bash
pip install -e ".[all,dev]"
ruff check src tests
pytest -q
```

## 라이선스

소스공개형 독점 라이선스입니다. PlateerLab 조직원은 플래티어 제품 범위에서 쓸 수 있습니다. [LICENSE](LICENSE) 를 보세요.
