# AI 쇼핑몰 — 설계 인계 04: 실험·검증 (v1.7)

> ⚠️ 모든 코드 검증은 rdflib **드라이런** (룰엔진/RDB를 동등 코드로 대체). 실제 Fuseki·Qwen·클러스터 검증은 미수행.

## 산출물

### v1.5 산출물 (ontology/ · src/ 에 직접 투입)
| 파일 | 위치 | 내용 |
|---|---|---|
| pc-schema.ttl | ontology/ | 온톨로지 스키마 (TBox + 통제어휘 개체) |
| pc-compat.rules | ontology/ | 호환 5규칙 (Jena 룰 형틀, 4슬롯·2패턴) |
| pc-sample-data.ttl | ontology/ | legacy 샘플 (parts.yaml 로 대체, 보관용) |
| validate.py | src/ | 5규칙 머티 + Q1~Q5 SPARQL 드라이런 |
| tools.py | src/ | SPARQL 파라미터 도구 5개 + 가드 |
| rdb_boundary.py | src/ | RDB 경계(sqlite) + 가격조인 |
| agent_loop.py | src/ | 에이전트 루프 (LLM 의도 스텁, 루프 기계장치) |

### v1.6 산출물 (작업5, 저장소에 커밋됨)
| 파일 | 위치 | 내용 |
|---|---|---|
| parts.yaml | data/ | 부품 단일 출처 (26종, IRI 명시) |
| load.py | src/ | parts.yaml → pc-data.ttl + catalog.sqlite (불변식 4종 강제) |
| verify_task5.py | src/ | 확대 데이터로 Q1~Q5 + RDB 후필터 재검증 |

## 작업5: 데이터 출처·적재 ✅ (v1.6 완료)

**단일 출처 → 분기 적재 구조**: `parts.yaml` → `load.py` → `pc-data.ttl`(Fuseki) + `catalog.sqlite`(RDB). 다리 = IRI. 한 출처라 IRI 드리프트 0.

**적재 불변식 (load.py 기계 체크, 위반 시 적재 실패)**
1. 모든 GPU `powerMargin` 보유
2. `incompatibleWith` 예외 정확히 1쌍
3. IRI 유일
4. 온톨로지 IRI 집합 == RDB IRI 집합 (다리 정합)

**데이터 설계 의도 (검증 케이스 내장)**
- 멀티플랫폼: AM5(Ryzen) + LGA1700(Intel) 양쪽 CPU/MB → Q3 정답이 여러 세트
- 전력 경계 510: gpu_rtx4080 (rec 450 + margin 60 = 510). psu_510w 통과(≥), psu_500w 탈락
- Q4 예외: cpu_i5_14600k ↔ mb_b760_ddr4 (소켓 LGA1700 일치, incompatibleWith 명시)

## 검증 질의 5종 (성공조건) — 드라이런 전부 통과 ✅

| 질의 | 검증 내용 | 결과 |
|---|---|---|
| Q1 소켓 매칭 | 7700X(AM5) → b650, x670e만 | ✅ |
| Q2 전력 임계값(≥) | 4080(필요510) → 510통과·500탈락 | ✅ |
| Q3 다중제약 견적 | 4080 앵커 → 144세트, AM5+LGA1700 둘 다 | ✅ |
| Q4 예외 우선순위 | 소켓공유=True인데 socketCompatible 미도출 | ✅ |
| Q5 설명가능성 | basis: wattage 510 ≥ rec+margin 510 | ✅ |
| RDB 경계 | 가격변경 후 재머티리얼라이즈 0회 | ✅ |

**진단맵** (실제 Fuseki에서 실패 시):
- Q1·Q2 실패 → 기초추론 문제
- Q3 실패 → 조합·하이브리드 문제
- Q4 실패 → 표현력 한계
- Q5 실패 → LLM↔추론사실 연결 문제

**최종 성공 기준**: LLM → SPARQL → 추론사실조회 → 자연어답변 한 바퀴 완주 + 추론지연·재추론시간·SPARQL 응답속도 **실측치** 확보.

## 미해결 운영 전제 (실제 환경에서만 검증 가능)

## 운영 전제 진행상태 (v1.7 갱신)

| # | 항목 | 상태 | 비고 |
|---|---|---|---|
| 1 | Fuseki 실측치 (추론지연·재추론시간·SPARQL 응답속도) | ⬜ **미완 — 다음 작업** | 드라이런으론 불가. 클러스터에 Fuseki 띄우고 실측 |
| 2 | vLLM tool calling 동작 + `--tool-call-parser` 값 | ✅ **실측통과** | parser=`qwen3_coder`, reasoning-parser=`qwen3`. probe Stage1·2 PASS. fallback 불필요(코드는 보존) |
| 3 | 클러스터 → GB10 연결 | ◐ **도달 확인, Service 등록만 남음** | tailnet 경유 `/v1/models`·tool-call 왕복 OK. vllm-svc ExternalName 등록 실행만 |

### 전제2 실측 산출물 (v1.7)
- `src/probe_toolcalling.py` — GB10 vLLM tool-calling 라이브 프로브 (Stage0 도달 / Stage1 파서 / Stage2 루프-정합). API키는 `GB10_API_KEY` 환경변수로.
- 결과: Stage1 구조화 tool_calls 정상, Stage2 `resolve_entity` 선행 호출(불변식 정합). 상세 01-infra.

### 전제3 도달 메모
- VM(클러스터)에 tailscale 설치 → GB10(`100.82.135.124`) 직통. 브리지 불필요.
- 다음: `vllm-svc`(ExternalName 또는 고정 Endpoints) 등록 → 앱이 `vllm-svc`로 호출(이식성).

## 다음 세션 권장
지참 파일: `00-overview.md` + `01-infra.md` + `04-experiment.md`

순서:
1. **(전제1)** 클러스터에 Fuseki 띄우기 → `python src/load.py` → 생성된 `pc-data.ttl` Fuseki에 POST
2. **(전제1)** Q1~Q5 실측 (추론지연·재추론시간·SPARQL 응답속도 수치 확보). 진단맵으로 실패 위치 판정
3. **(전제3 마무리)** vllm-svc 등록 + 앱에서 호출 확인
4. 위 통과 시 → 한 바퀴 통합(LLM→SPARQL→추론조회→자연어) 후 클러스터 배포
