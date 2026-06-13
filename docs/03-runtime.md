# AI 쇼핑몰 — 설계 인계 03: 런타임 (v2.2)

## 런타임 구조 (확정)
```
사용자 자연어
 → LLM(Qwen): 의도해석 → 도구/파라미터로 매핑
 → 도구 호출: 파라미터화 SPARQL/SQL 실행 (사전추론된 사실 위에서 조회)
 → LLM(Qwen): 결과(basis 포함)를 자연어로 종합·설명
```
- 무거운 논리추론 = 추론기(오프라인 사전추론), 자연어↔구조화질의 = LLM.
- **LLM에 raw SQL/SPARQL 직접 생성 금지** → 파라미터만 채움.

## 작업2: SPARQL 파라미터 도구 (5종 완비) — `src/tools.py`

| 도구 | 용도 | 상태 |
|---|---|---|
| resolve_entity | 텍스트 → IRI (유일 출처) | ✅ v2.1 정규화 |
| find_compatible | 카테고리쌍 + 앵커 IRI → 호환 목록 (10쌍) | ✅ v2.1 FILTER NOT EXISTS |
| check_compatibility | 두 IRI 간 호환 여부 + 사유 (예외 우선) | ✅ v2.1 |
| build_configuration | 앵커 GPU IRI → 완전 견적 세트 | ✅ v2.2 |
| explain_fact | (subject, predicate, object) → 도출 근거 | ✅ v2.2 |
| get_product_info | IRI 목록 → RDB 상세(가격·재고·평점·SKU) | ✅ v2.4 — 호환성 아닌 카탈로그 사실 질의용. rdb-svc `/info` 호출 |

### resolve_entity — v2.1 정규화
- needle·IRI 양쪽을 `REPLACE(…, "[^a-z0-9]", "")` 후 CONTAINS 비교. `i5-14600K`/`cpu_i5_14600k` → `i514600k` 매칭.
- ⚠️ **한글 needle gap (v2.2 기록, 미수정)**: 한글만 있는 needle은 `[^a-z0-9]` 제거 후 `""` → `CONTAINS(x, "")`는 항상 참 → 카테고리 내 임의 항목이 `LIMIT 1`로 집힘. "미들타워/풀타워" 무성 오답 표면. 후보 fix: (a) 빈 needle 거부, (b) RDB 표시명 검색 폴백. → 한글 표시명 전반 문제이지 mid/full 한정 아님.

### find_compatible — v2.1 FILTER NOT EXISTS
- 모든 쿼리에 양방향 incompatibleWith 필터 (추천 도구이므로 예외 제외).

### build_configuration — v2.2
- 입력: `anchor_iri` (GPU). 출력: `{configurations:[{mb,case,cpu_options,ram_options}], psu_options, basis, pair_count}`.
- 구조 조인(case/mb/cpu/ram) + cpu↔mb incompatibleWith 필터. **PSU는 별도 쿼리**(inner-join 붕괴 방지: "PSU 0개"가 "구성 0개"로 오인되지 않게).
- cpu/ram은 (mb,case) 쌍별로 묶음(MB 종속 — 합집합으로 펴면 잘못된 조합 제시 위험). psu만 플랫(GPU 종속).

### explain_fact — v2.2
- 입력: `(subject_iri, predicate, object_iri)` 3개 전부 (object 자동도출 안 함). predicate ∈ 5도출술어 + incompatibleWith 닫힌 enum.
- 출력: `{holds, premises, basis_detail}`. 두 IRI `_validate_iri`, 미지 predicate → error.
- 패턴: 공유개체형(socket/ram/formfactor) → 양쪽 소스속성 / 수치형(power/gpufit) → 소스 수치 + 부등식. premises에 raw 수치 보존 → LLM이 구체 숫자 인용.
- **책임 경계**: explain_fact = 단일 사실 근거. check_compatibility = 종합 판정 with 예외 우선. explain은 예외를 끌어오지 않음(겹침 방지).

### 불변 규칙
- 모든 가변값은 whitelist 검증 후 인라인 주입 (initBindings object 위치 미전파 이슈).
- **IRI 유일 출처 = resolve_entity**. 나머지 도구는 세션 미등록 IRI 거부.
- `relation`/`predicate`는 카테고리쌍 자동도출 또는 닫힌 enum. `category`는 6종 닫힌 enum.

## 작업3: RDB vs 온톨로지 경계 — `src/rdb_boundary.py`
(변경 없음 — v1.9 참조. `resolve_display_names(iris)` IRI→표시명 룩업.)

## 작업4: 에이전트 루프 — `src/agent_loop.py`

### 루프 / 불변식 4개
1. 세션에 surface된 IRI만 통과 (날조 거부 → 자기교정)
2. raw 쿼리 도구 부재
3. 도구는 결정적, 비결정성은 의도해석/종합에만
4. 최대 호출 깊이 상한 (MAX_DEPTH=8)

### 종합 규칙 (SYSTEM 프롬프트)
- find_compatible: 첫 문장에 basis(호환 술어) 명시.
- check_compatibility: basis_detail 인용 / compatible·explicitly_incompatible 분기.
- build_configuration: 5규칙 basis 명시 / pair_count 조합 + CPU·RAM·PSU 표시명 / configurations·psu_options 빈 경우 구분.
- explain_fact: premises의 구체 수치를 응답에 인용 (술어이름=사유 원칙의 마지막 한 겹).

### `<think>` strip (v2.2)
- `_strip_think()` 를 루프 종합 직전 적용. reasoning-parser(qwen3)가 분리 못하고 content로 샌 케이스 방어. 완전블록 + open소실/close잔존 둘 다 처리. (v1.9 "분리 작동" 관찰이 이 경로에선 content 누수로 나타남.)

### _enrich
- find_compatible 결과: `results` IRI → 표시명. resolve_entity 결과는 원형 보존(자기교정).
- build_configuration 결과: `_enrich_build` — configurations 중첩 IRI + psu_options 일괄 치환.

## 배포 형상 (v2.2 갱신)
- `k8s/agent-deploy.yaml` = Deployment(`python:3.12-slim`, `sleep infinity`) + initContainer(`pip install --target=/deps`) + ConfigMap `agent-code`(src + requirements.txt + catalog.sqlite) + Secret `vllm-api-key`→env `VLLM_API_KEY`.
- **코드/데이터 갱신**: `kubectl create cm agent-code --from-file=… --dry-run=client -o yaml | kubectl apply -f -` **만**.
  - ⚠️ **`rollout restart` 불필요** (v2.2 정정): ConfigMap 볼륨 마운트 자동 갱신 + per-`exec` 실행 모델 → 다음 `exec`가 새 코드 픽업. restart는 **initContainer(pip 의존성) 변경 시에만**. 불필요한 restart는 CoreDNS-trap 리스크만 추가.
- 검증: `verify_q3.py`(Q3 건전성), `verify_fuseki.py`(Q1~Q5 라이브), agent_loop 직접 exec.

## 작업6: 웹 서비스 + 역할분리 토폴로지 (v2.4) — `src/server.py`·`src/rdb_service.py`·`web/index.html`
브라우저에서 온톨로지 추론을 종단까지 보는 라이브 데모. **GB10 Qwen이 의도해석·도구호출·종합**, Fuseki가 룰추론.

### 4계층 역할분리 (각 역할 = 독립 Deployment+Service)
```
브라우저 → web-svc(NodePort 30080)
              │  UI 서빙 + 에이전트 루프 + 온톨로지 클라이언트(tools/SPARQL)
              ├─ rdb-svc:8081      표시명·가격 (관계형 데이터 단독 권한자)
              ├─ fuseki-svc:3030   룰추론 (온톨로지 트리플스토어 + GenericRuleReasoner)
              └─ vllm-svc:8000     GB10 Qwen3.6-35B-A3B (tailnet, 외부)
```
- **`src/server.py`** (web) — stdlib `http.server`(ThreadingHTTPServer, 의존=openai·rdflib·yaml). 요청별 `AgentSession` → 세션 상태 격리.
  - `GET /` index.html / `GET /api/catalog` [onto 스펙(parts.yaml) ⨝ 관계형(rdb-svc)] 머지 / `GET /api/health`(rdb up/down 포함) / `POST /api/ask {q}` → `{answer, trace, turns, tool_calls, engine}`.
  - 트레이스에는 **IRI 보존 RAW 결과**를 담아 프런트가 카드를 그림(LLM 에는 `_enrich` 표시명본을 넘김).
  - `/api/catalog` 의 `rel_source` 가 `rdb-svc` 면 경계 라이브, `fallback(parts.yaml)` 이면 rdb 다운.
- **`src/rdb_service.py`** (rdb) — **stdlib only, 무의존**(initContainer 불필요). catalog.sqlite 의 단독 권한자.
  - `GET /health` / `GET /catalog`(관계형 행) / `POST /resolve-names {iris}` → `{iri: display_name}`(미스 시 IRI 원본).
- **`src/rdb_boundary.py` (v2.4 변경)** — sqlite 직접 열기 폐기 → **rdb-svc HTTP 클라이언트**. `resolve_display_names(iris)` 시그니처 보존(tools/agent_loop 무변경). rdb 장애 시 IRI 폴백(degraded).
- **`agent_loop.py` (v2.4 리팩터)** — 전역 `_session_iris`/`_dispatch` 폐기 → **`AgentSession` 클래스**(`.iris`/`.trace`/`.run`). 동시요청 누수·경합 제거. 모듈 `run()` = CLI 하위호환 래퍼.
- **`web/index.html`** — B안 데모 UI 재사용. `/api/catalog` 로 카드, `/api/ask` 로 답+실 트레이스 렌더. Claude 호출 전부 제거(운영=GB10).
- **온톨로지 그래프** (`web/ontology.html` + `GET /ontology`, `GET /api/graph`) — Fuseki 라이브 트리플을 노드-엣지로 시각화(바닐라 JS 포스 레이아웃, 무의존). 부품→통제어휘(소켓·RAM타입·폼팩터) **공유 엣지(기반사실)** + 추론기 머티리얼라이즈 **호환 엣지(추론, 토글)** + **incompatibleWith(예외, 빨간 점선)**. 부품 라벨은 RDB 표시명. 노드 드래그·레이어 토글·재배치. 메인 헤더에서 링크.

### 배포 형상
- `k8s/rdb-deploy.yaml` = Deployment `rdb`(app=rdb, `python /code/rdb_service.py`, 8081, readinessProbe `/health`) + Service `rdb-svc`(ClusterIP 8081). initContainer/deps 볼륨 없음(stdlib).
- `k8s/web-deploy.yaml` = Deployment `web`(app=web, `python /code/server.py`, 8080, initContainer pip, env RDB_URL/FUSEKI_URL/VLLM_*) + Service `web-svc`(NodePort **30080**). 접근: `http://192.168.56.10:30080/`.
- 둘 다 같은 ConfigMap `agent-code` 마운트(코드 단일 출처). **복붙 배포 명령 전체는 `README.md` → 실행 2(클러스터 배포)** 참조 — 15개 `--from-file`(py 10 + html 2 + requirements + parts.yaml + catalog.sqlite), **Bash 파이프**(UTF-8 보존).
- ~~구 `agent-deploy.yaml`/`agent-svc.yaml`~~ 삭제(web/rdb 로 대체).
- **재배포 규칙**: ConfigMap 재생성 후 — `server.py`/`agent_loop.py` 등 임포트 모듈 변경 → `rollout restart deploy/web` 필수(장기구동 서버는 자동 리로드 안 됨) / `web/*.html` 만 변경 → 재시작 불필요(`do_GET` 이 매 요청 파일을 새로 읽음, ~10~40초 내 반영).
- 검증(라이브, 호스트에서): `/api/health rdb=up` · `/api/catalog rel_source=rdb-svc` · `POST /api/ask` Q3/Q4 정답.
- 참고: 한때 Calico CNI `Unauthorized` 로 롤아웃 불가했으나(2026-06-11 Calico 파드 재시작으로 해소) 현재 정식 Deployment 롤아웃으로 가동.

### 시연 — 토큰·비용 패널 (web UI)
- `POST /api/ask` 응답에 `tokens`{`input`,`output`,`total`,`query_tokens`,`raw_prompt`,`raw_completion`,`turns[]`} 포함. `server.py: token_summary()` 가 턴별 usage 누계 + vLLM `/tokenize` 로 질문 토큰 실측.
- **입력 = 사용자 질문만 / 출력 = 답을 내기까지 그 외 전부(시스템 프롬프트·도구정의·N턴 재전송·도구결과·생성)** — "질문 1줄인데 답까지 이만큼" 연출.
- **비용 환산**은 실제 과금 기준(`raw_prompt`=입력가, `raw_completion`=출력가)으로 Claude(Opus4.8/Sonnet4.6/Haiku4.5)·GPT(4o/4o-mini) 단가표 표시. 단가·환율은 `web/index.html` 상단 `PRICING`/`FX_KRW` 상수에서 수정.
