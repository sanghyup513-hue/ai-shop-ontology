# AI 쇼핑몰 — 설계 인계 04: 실험·검증 (v1.8)

> ⚠️ v1.5/1.6 시점의 코드 검증은 rdflib **드라이런** (룰엔진/RDB를 동등 코드로 대체).
> v1.7: Qwen tool-calling·GB10 도달 실측 통과.
> **v1.8: 전제1 Fuseki도 실측 통과** — 5규칙 라이브 발화·Q1~Q5 결과 드라이런과 일치. 드라이런 자체는 이력으로 보존(설계 의도는 드라이런으로 굳혀졌고, 실측이 이를 확인). **남은 미실측: 전제3 마무리(vllm-svc) + 한 바퀴 통합.**

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

### v1.8 산출물 (전제1 실측, 저장소에 커밋됨)
| 파일 | 위치 | 내용 |
|---|---|---|
| pc-compat.rules | ontology/ | Jena GenericRuleReasoner용 5규칙(설계대로 코드화). v1.5에서 설계만 있던 것을 실파일로 |
| fuseki-assembler.ttl | k8s/ | InfModel(베이스+규칙) → Dataset → Service 어셈블러. 베이스=인메모리 + `pc-data.ttl` ja:externalContent |
| fuseki-deploy.yaml | k8s/ | Deployment(`stain/jena-fuseki` 5.1.0) + NodePort Service(30030). ConfigMap `fuseki-config` 마운트 |
| verify_fuseki.py | src/ | Q1~Q5 라이브 SPARQL 검증 + cold/warm 타이밍 측정 스크립트 |

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

## 검증 질의 5종 (성공조건) — 드라이런 통과 ✅ + **v1.8 Fuseki 실측 통과 ✅**

| 질의 | 검증 내용 | 드라이런 | Fuseki 실측(v1.8) |
|---|---|---|---|
| Q1 소켓 매칭 | 7700X(AM5) → b650, x670e만 | ✅ | ✅ (정확 2건) |
| Q2 전력 임계값(≥) | 4080(필요510) → 510통과·500탈락 | ✅ | ✅ (510/550/750/1000 통과, 500 탈락) |
| Q3 다중제약 견적 | 4080 앵커 → ATX 보드 4종 × 케이스 2종 = 8건, AM5+LGA1700 둘 다 | ✅ | ✅ (8건 도출) |
| Q4 예외 우선순위 | i5_14600k↔b760_ddr4: 소켓공유=True인데 socketCompatible 미도출 | ✅ | ✅ (미도출 확인. 비교군 i7_14700k↔b760_ddr4 는 도출 → 예외만 정확히 차단) |
| Q5 설명가능성 | gpuFitsCase: 4080(310mm) → full+mid 케이스 | ✅ | ✅ (full/mid 2건) |
| RDB 경계 | 가격변경 후 재머티리얼라이즈 0회 | ✅ | (변경 없음) |
| ramCompatible(추가) | DDR4 RAM 2개 → 1보드, DDR5 RAM 2개 → 4보드 | ✅ | ✅ (10건 정확) |

**진단맵** (실제 Fuseki에서 실패 시):
- Q1·Q2 실패 → 기초추론 문제
- Q3 실패 → 조합·하이브리드 문제
- Q4 실패 → 표현력 한계
- Q5 실패 → LLM↔추론사실 연결 문제

**최종 성공 기준**: LLM → SPARQL → 추론사실조회 → 자연어답변 한 바퀴 완주 + 추론지연·재추론시간·SPARQL 응답속도 **실측치** 확보.

## 운영 전제 진행상태 (v1.8 갱신)

| # | 항목 | 상태 | 비고 |
|---|---|---|---|
| 1 | Fuseki 실측치 (추론지연·재추론시간·SPARQL 응답속도) | ✅ **실측통과** | Jena 5.1.0 + GenericRuleReasoner(hybrid 기본 모드, noValue/sum/ge/le 작동). 클러스터 파드 라이브 추론. **cold 150ms / warm 39ms / 추론비용 110ms** (26부품/81트리플/5규칙). 5규칙 전부 발화 + Q1~Q5 드라이런 결과와 일치 |
| 2 | vLLM tool calling 동작 + `--tool-call-parser` 값 | ✅ **실측통과** | parser=`qwen3_coder`, reasoning-parser=`qwen3`. probe Stage1·2 PASS. fallback 불필요(코드는 보존) |
| 3 | 클러스터 → GB10 연결 | ◐ **도달 확인, Service 등록만 남음** | tailnet 경유 `/v1/models`·tool-call 왕복 OK. vllm-svc ExternalName 등록 실행만 |

### 전제1 실측 산출물 (v1.8)
- `ontology/pc-compat.rules` — 5규칙 Jena 룰 코드화 (sum/ge/le는 쉼표 인자 형식 `sum(?a, ?b, ?c)`). hybrid 기본 모드에서 noValue·sum·ge·le 모두 정상.
- `k8s/fuseki-assembler.ttl` — `ja:InfModel`(베이스 + GenericRuleReasoner) → `ja:RDFDataset` → `fuseki:Service` 어셈블러.
- `k8s/fuseki-deploy.yaml` — Deployment(`stain/jena-fuseki` 5.1.0, `--config=` 플래그로 어셈블러 지정) + ConfigMap 3파일 마운트 + NodePort 30030.
- `src/verify_fuseki.py` — Q1~Q5 SPARQL + cold/warm 타이밍 측정.
- **이미지 선택 사유:** `apache/jena-fuseki:*` Docker Hub 풀이 `insufficient_scope` 로 실패(현 시점). `stain/jena-fuseki`(Fuseki 5.1.0 동등 이미지)는 정상 풀됨 → 이쪽 채택.

### 전제1 결과 한계 (인지)
- 26부품 규모. **"되냐"는 확인됐고, "규모가 커지면 추론비용이 어떻게 커지냐"는 미검** — 이번 실험 범위 밖. 운영 데이터(예: 1만 부품) 적재 시 cold·재추론 시간은 재측정 필요.
- 측정은 NodePort 경유 외부 → 클러스터 내부 호출 시 네트워크 오버헤드 더 작을 것.

### 전제2 실측 산출물 (v1.7)
- `src/probe_toolcalling.py` — GB10 vLLM tool-calling 라이브 프로브 (Stage0 도달 / Stage1 파서 / Stage2 루프-정합). API키는 `GB10_API_KEY` 환경변수로.
- 결과: Stage1 구조화 tool_calls 정상, Stage2 `resolve_entity` 선행 호출(불변식 정합). 상세 01-infra.

### 전제3 도달 메모
- VM(클러스터)에 tailscale 설치 → GB10(`100.82.135.124`) 직통. 브리지 불필요.
- 다음: `vllm-svc`(ExternalName 또는 고정 Endpoints) 등록 → 앱이 `vllm-svc`로 호출(이식성).

## 다음 세션 권장
지참 파일: `00-overview.md` + `01-infra.md` + `04-experiment.md`

순서:
1. **(전제3 마무리)** `vllm-svc` ExternalName(또는 고정 Endpoints) 등록 → 클러스터 내부 파드에서 `http://vllm-svc:8000/v1/models` 도달 확인.
2. **(통합 한 바퀴)** Fuseki(클러스터 내) + GB10(외부) + 에이전트 루프를 한 파드에서 묶기 → NL 한 줄("4080에 맞는 메인보드 추천") → LLM 의도 → resolve+find_compatible → 자연어 종합. Q1~Q5 자연어로 완주.
3. **(스케일링 미검)** 데이터 확대 시(>1000부품) cold 추론비용·warm 재측정. 추론이 사실상 선형 머티이므로 비용은 입력 트리플 수에 비례 예상 — 실측 필요.
4. 위 통과 시 클러스터 배포(이미지 빌드·Deployment 다중 컴포넌트).
