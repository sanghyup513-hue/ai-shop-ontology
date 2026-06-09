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
