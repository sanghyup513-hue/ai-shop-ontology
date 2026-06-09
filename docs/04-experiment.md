# AI 쇼핑몰 — 설계 인계 04: 실험·검증 (v2.0)

> v1.8: Fuseki 실측 통과.
> v1.9: 통합 한 바퀴 Q1 경로 실인프라 완주.
> **v2.0: find_compatible 10쌍 실가동. Q2(gpu→psu 역방향)·Q5(gpu→case 정방향) 자연어 완주.**
> CoreDNS upstream 8.8.8.8 전환 / Fuseki imagePullPolicy:IfNotPresent 안정화.
> **남은 미실측: Q3(build_configuration)·Q4(check_compatibility) 자연어.**

## 산출물

### v1.5 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| pc-schema.ttl | ontology/ | 온톨로지 스키마 |
| pc-compat.rules | ontology/ | 호환 5규칙 |
| validate.py | src/ | 5규칙 머티 + Q1~Q5 드라이런 |
| tools.py | src/ | SPARQL 파라미터 도구 (v2.0에서 확장) |
| rdb_boundary.py | src/ | RDB 경계(sqlite) |
| agent_loop.py | src/ | 에이전트 루프 (v2.0에서 확장) |

### v1.6 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| parts.yaml | data/ | 부품 단일 출처 (26종) |
| load.py | src/ | parts.yaml → pc-data.ttl + catalog.sqlite |
| verify_task5.py | src/ | Q1~Q5 + RDB 후필터 재검증 |

### v1.8 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| pc-compat.rules | ontology/ | Jena GenericRuleReasoner용 5규칙 |
| fuseki-assembler.ttl | k8s/ | 어셈블러 |
| fuseki-deploy.yaml | k8s/ | Fuseki Deployment + NodePort |
| verify_fuseki.py | src/ | Q1~Q5 라이브 검증 + 타이밍 |

### v1.9 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| vllm-svc.yaml | k8s/ | 헤드리스 Service + 수동 Endpoints |
| agent-deploy.yaml | k8s/ | Deployment + initContainer + Secret |
| tools.py (슬라이스) | src/ | resolve_entity·find_compatible 2도구 |
| agent_loop.py (슬라이스) | src/ | GB10 실호출·_enrich·VLLM_API_KEY |
| rdb_boundary.py | src/ | resolve_display_names |

### v2.0 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| tools.py | src/ | find_compatible **10쌍** 확장 (RELATION_MAP + 정/역 템플릿) |
| agent_loop.py | src/ | SYSTEM 프롬프트 10쌍 보강 (Q2/Q5 예시 포함) |
| fuseki-deploy.yaml | k8s/ | `imagePullPolicy: IfNotPresent` 추가 |

## 검증 질의 5종 현황

| 질의 | 검증 내용 | 드라이런 | Fuseki 실측 | 자연어 완주 |
|---|---|---|---|---|
| Q1 소켓 매칭 | 7700X → b650·x670e | ✅ | ✅ | ✅ v1.9 |
| Q2 전력 임계값 | 4080(필요510) → 510통과·500탈락 | ✅ | ✅ | ✅ **v2.0** (4건+basis) |
| Q3 다중제약 견적 | 4080 앵커 → ATX 보드 × 케이스 = 8건 | ✅ | ✅ | ⬜ |
| Q4 예외 우선순위 | i5_14600k↔b760_ddr4: socketCompatible 미도출 | ✅ | ✅ | ⬜ |
| Q5 설명가능성 | gpuFitsCase: 4080(310mm) → full+mid | ✅ | ✅ | ✅ **v2.0** (2건+basis) |

## 운영 전제 진행상태

| # | 항목 | 상태 |
|---|---|---|
| 1 | Fuseki 실측치 | ✅ cold 150ms / warm 39ms / 추론비용 110ms |
| 2 | vLLM tool calling | ✅ parser=qwen3_coder |
| 3 | 클러스터 → GB10 | ✅ vllm-svc 수동Endpoints |

## v2.0 라이브 결과 (메모)
- Q2: "RTX 4080에 맞는 파워" → resolve_entity(gpu) → find_compatible(gpu,psu) → powerSufficient 역방향 → 4건 → 표시명 + basis 종합 ✅
- Q5: "RTX 4080이 들어가는 케이스" → resolve_entity(gpu) → find_compatible(gpu,case) → gpuFitsCase → 2건 → basis 종합 ✅
- **CoreDNS 이슈**: `.71/.72` upstream rotate 사망 → Corefile `forward . 8.8.8.8 8.8.4.4` 패치 → pypi.org 해석 복구. Vagrant 재현 시 8.8.8.8 직접 기입 필요.

## 테스트 brittleness (v1.9 발견, 미수정)
- verify_fuseki의 expected 가 parts.yaml 비파생 손-리터럴 → 데이터 확장 시 드리프트.
- Q1·Q2_pass·Q5 는 `==` 정확일치라 새 부품 추가 시 FAIL.
- 근본수정(미정): expected를 parts.yaml 파생으로.

## 다음 세션 권장
지참 파일: `00-overview.md` + `03-runtime.md` + `04-experiment.md`

순서:
1. **(Q4 자연어)** check_compatibility 구현 → 두 IRI 간 호환여부 + incompatibleWith 예외 우선순위.
2. **(Q3 자연어)** build_configuration 구현 → GPU 앵커 → 완전 견적 세트.
3. **(Q3/Q4 이후)** explain_fact → Q5 설명가능성 강화.
4. **(미반입 코드 정리)** validate.py·probe_toolcalling.py.
5. **(테스트 견고화)** expected → parts.yaml 파생.
6. **(스케일링 미검)** >1000부품 cold·재추론 재측정.
