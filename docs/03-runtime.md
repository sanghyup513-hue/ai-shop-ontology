# AI 쇼핑몰 — 설계 인계 03: 런타임 (v1.9)

## 런타임 구조 (확정)
```
사용자 자연어
 → LLM(Qwen): 의도해석 → 도구/파라미터로 매핑
 → 도구 호출: 파라미터화 SPARQL/SQL 실행 (사전추론된 사실 위에서 조회)
 → LLM(Qwen): 결과(basis 포함)를 자연어로 종합·설명
```
- 무거운 논리추론 = 추론기(오프라인 사전추론), 자연어↔구조화질의 = LLM.
- **LLM에 raw SQL/SPARQL 직접 생성 금지** → 파라미터만 채움.

## 작업2: SPARQL 파라미터 도구 (확정·검증) — `src/tools.py`

### 도구 5개 (고정 파라미터화 쿼리)
| 도구 | 용도 |
|---|---|
| resolve_entity | 텍스트 → IRI (유일 출처) |
| find_compatible | 카테고리쌍 + 앵커 IRI → 호환 목록 |
| check_compatibility | 두 IRI 간 호환 여부 + 사유 |
| build_configuration | 앵커 GPU IRI → 완전 견적 세트 |
| explain_fact | IRI + 도출술어 → 근거(basis_detail) |

- v1.9 실재: tools.py 신규 작성, **5도구 중 2도구(resolve_entity·find_compatible)만 슬라이스 구현**. 나머지 3(check_compatibility·build_configuration·explain_fact) 미구현. find_compatible은 (cpu→motherboard) 정방향만(socketCompatible). 역방향·타 카테고리쌍 미구현.

### 불변 규칙
- 모든 가변값은 `initBindings`(바인딩)로만 주입 → 쿼리 텍스트에 LLM 입력 0.
- **IRI 유일 출처 = resolve_entity**. 나머지 도구는 미지 IRI 거부 (환각 차단).
- `relation`은 LLM 비노출 → (anchor, target) 카테고리쌍에서 앱이 자동 도출 (정/역 방향 포함).
- `category`는 6종 닫힌 enum. 위반 즉시 거부.

## 작업3: RDB vs 온톨로지 경계 (확정·v1.9 실재화) — `src/rdb_boundary.py`

### 판정 규칙
| 저장소 | 데이터 | 변경 시 |
|---|---|---|
| 온톨로지 (Fuseki) | 추론용 스펙·도출술어·예외·IRI/타입 | 재추론 필요 |
| RDB (sqlite → Postgres) | 가격·재고·SKU·표시명·이미지·평점 | 재추론 불필요 |

- **다리 = IRI 하나.** 온톨로지 질의 → IRI → 앱이 RDB 조회.
- 흐름: 온톨로지 우선(하드제약) → RDB 후필터(가격/재고).
- SQL도 LLM 비노출 (고정 SQL + 바인딩, IN 자리수만 구조적).
- 운영 이식: sqlite → Postgres 등 교체해도 쿼리 동일.
- 검증: "80만원대 보드" 후필터 동작 + **가격만 변경 시 재머티리얼라이즈 0회** 실증 ✅
- **v1.9 실재화**: `resolve_display_names(iris) -> {iri: display_name}` 구현. PC 접두어 자동 절단 후 `catalog.iri`(localname) IN 매칭. 미스 시 IRI 원본을 그대로 값으로(LLM 종합 단계의 안전성). `CATALOG_DB` env로 경로 외부화 (`/code/catalog.sqlite` ← ConfigMap 동봉).

## 작업4: 에이전트 루프 (확정·검증) — `src/agent_loop.py`

### 루프
```
NL → [LLM 의도해석] → [앱: resolve → 도구 실행] → [LLM 종합/설명]
```

### 불변식 4개
1. 세션에 surface된 IRI만 통과 (날조 거부 → 자기교정)
2. raw 쿼리 도구 부재
3. 도구는 결정적, 비결정성은 의도해석/종합에만
4. 최대 호출 깊이 상한

### 기타
- 종합은 `basis` / `basis_detail`만 사용 → 근거기반·추적가능(Q5).
- 세션 상태 운반: 후속질문(Q5)이 직전 견적의 IRI 참조.
- **vLLM tool calling 미지원 시 fallback**: LLM이 `{intent, params}` JSON 방출 → 앱이 도구 매핑. 루프 모양 동일, transport만 교체.
  - v1.9 실측: tool-calling이 **실루프에서 종단 동작**(parser=qwen3_coder). NL→resolve 툴콜→surface→find 툴콜→종합까지 LLM이 스스로 연쇄. `</think>` 미등장(reasoning-parser qwen3 분리 작동). ⇒ fallback 영구 불필요(코드는 안전망 보존). agent_loop.py 신규 작성(스텁 제거, GB10 실호출).
- **표시명 후처리 (v1.9)**: `_enrich(tool_result)` — `results: [IRI]`를 `resolve_display_names`로 치환해 LLM에 전달. `basis` 등 다른 필드 보존. resolve_entity 결과는 원형 보존(단일 IRI는 자기교정 흐름에 사용). SYSTEM 프롬프트가 (a) 응답 첫 문장에 basis 명시, (b) results 항목을 표시명으로 그대로 사용, (c) 원시 IRI 비노출을 강제.
- **배포 형상 (v1.9)**: `k8s/agent-deploy.yaml` = Deployment(`python:3.12-slim`, `sleep infinity`) + initContainer(`pip install --target=/deps`) + ConfigMap `agent-code`(src 3종 + requirements.txt + catalog.sqlite 동봉). Secret `vllm-api-key/key` → env `VLLM_API_KEY` 주입. 코드/데이터 갱신 루프: `kubectl create cm … --dry-run=client -o yaml | kubectl apply -f -; kubectl rollout restart deploy/agent`.
- 검증: Q1~Q5 + 자기교정(날조 IRI 거부 → resolve 재시도 → "카탈로그 없음") 통과 ✅. Q1 표시명+basis 라이브 통과 ✅ (v1.9).
