# AI 쇼핑몰 — 설계 인계 04: 실험·검증 (v2.3)

> v1.8: Fuseki 실측 통과. v1.9: 통합 한 바퀴 Q1 완주.
> v2.0: find_compatible 10쌍·Q2·Q5 자연어. v2.1: check_compatibility·Q4 / noValue 제거.
> v2.2: build_configuration·Q3 / explain_fact / verify_q3 건전성 가드 / `<think>` strip.
> **v2.3: brittleness 근본수정 완료 — Q3 완전성(verify_q3) + verify_fuseki 손-리터럴 해소(oracle.py, 견고화 #3). 기대값 전부 parts.yaml 단일출처 파생, 매직넘버 0.**
> **✅ 5도구 완비 + Q1~Q5 자연어 완주 → B안 운영 가능 검증 완료.**

## 산출물 (누적)

### v2.0 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| tools.py | src/ | find_compatible 10쌍 (RELATION_MAP + 정/역) |
| agent_loop.py | src/ | SYSTEM 10쌍 보강 |
| fuseki-deploy.yaml | k8s/ | imagePullPolicy: IfNotPresent |

### v2.1 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| tools.py | src/ | check_compatibility + find_compatible FILTER NOT EXISTS + resolve 정규화 |
| agent_loop.py | src/ | check_compatibility 스키마·디스패치·SYSTEM |
| pc-compat.rules | ontology/ | rule1 noValue 제거 |
| verify_fuseki.py | src/ | Q4 기대값 반전 |

### v2.2 산출물
| 파일 | 위치 | 내용 |
|---|---|---|
| tools.py | src/ | build_configuration + explain_fact (5도구 완비) |
| agent_loop.py | src/ | build/explain 스키마·디스패치·SYSTEM + `_enrich_build` + `_strip_think` |
| verify_q3.py | src/ | Q3 건전성 불변식 (매직넘버 0) |

### v2.3 산출물 (brittleness 근본수정 완료)
| 파일 | 위치 | 내용 |
|---|---|---|
| oracle.py | src/ | parts.yaml 단일출처 → 기대치 순수 파생(추론기 독립). socket/power/gpuFit/boardFit 규칙 재현 |
| verify_fuseki.py | src/ | 손-리터럴 폐기 → oracle 파생 기대값. Q3는 정보→8쌍 실검증. parts.yaml 미발견 시 SKIP→[ERROR]+exit1 |
| verify_q3.py | src/ | 완전성(verify_q3_completeness) — parts.yaml 파생 == build_configuration |

## 검증 질의 5종 현황 (전부 자연어 완주)

| 질의 | 검증 내용 | Fuseki 실측 | 자연어 완주 |
|---|---|---|---|
| Q1 소켓 매칭 | 7700X → b650·x670e | ✅ | ✅ v1.9 |
| Q2 전력 임계값 | 4080(필요510) → 510통과·500탈락 | ✅ | ✅ v2.0 |
| Q3 다중제약 견적 | 4080 앵커 → 보드×케이스 + CPU/RAM/PSU | ✅ | ✅ **v2.2** |
| Q4 예외 우선순위 | i5_14600k↔b760_ddr4: 소켓일치·예외우선 | ✅ | ✅ v2.1 |
| Q5 설명가능성 | gpuFitsCase: 4080(310mm) → full+mid | ✅ | ✅ v2.0 / explain_fact 수치강화 |

## v2.2 라이브 결과 (메모)
- **Q3**: "RTX 4080으로 견적" → resolve(gpu) → build_configuration → 5규칙 basis + 보드-케이스 **10쌍** + 표시명 종합 ✅. 예외쌍(i5_14600k↔b760_ddr4) cpu_options에서 제외 확인(Q4 회귀 없음). PSU 4건(1000/750/550/510W).
  - "10쌍"은 mb_b760_ddr4 추가로 8→10 (데이터 추가가 카운트 이동 — 정상). 리터럴 박지 않음.
- **explain_fact**: 6술어 직접 테스트 — socketCompatible(7700x,b650)→"공유 소켓 AM5", powerSufficient(510w,4080)→"510W ≥ 450+60=510W", 경계 psu_500w/rtx4090 → holds=False 정확.

## Q3 검증 = 건전성/완전성 분리 (brittleness 근본수정 — 완료)
- **카운트 == 리터럴 폐기.** 데이터 추가마다 깨지는 패턴(3회 발현)의 근본수정. step 1(Q3)·step 2(verify_fuseki) 둘 다 완료.
- **(1) 건전성 (verify_q3.py — 완료, parts.yaml 불필요, 매직넘버 0):**
  - 불변식0: pair_count 일관 + (mb,case) distinct
  - 불변식1: 각 쌍 gpuFitsCase ∧ boardFitsCase
  - 불변식2: cpu_option 전부 socketCompatible ∧ **incompatibleWith 누수 0** (Q4 회귀 가드)
  - 불변식3: ram_option 전부 ramCompatible / 불변식4: psu_option 전부 powerSufficient
  - → "반환된 게 전부 유효한가" (소건전성). ASK 쿼리 기반.
- **(2) 완전성 (verify_q3.py `verify_q3_completeness` — 완료):** "유효한 게 전부 반환됐나". parts.yaml lengthMm/maxGpuLengthMm·hasFormFactor/supportsFormFactor 독립 조인으로 기대 (mb,case)·옵션·PSU 파생 → build_configuration 결과와 set 비교. 누락(under-report)·과잉(over-report) 양방향 가드.
- **(3) verify_fuseki 손-리터럴 해소 (oracle.py — 완료, 견고화 #3):** Q1/Q2/Q3/Q5 기대값을 oracle.Oracle 이 parts.yaml 에서 파생. 추론 경로(데이터→TTL→Fuseki)와 독립 구현(데이터→기대)이 교차검증. parts.yaml 미발견 시 SKIP 아닌 [ERROR]+exit1(기대값 못 만들면 검증 불가 → 하드 실패).

## 운영 전제 진행상태
| # | 항목 | 상태 |
|---|---|---|
| 1 | Fuseki 실측치 | ✅ cold 150ms / warm 39ms / 추론비용 110ms |
| 2 | vLLM tool calling | ✅ parser=qwen3_coder |
| 3 | 클러스터 → GB10 | ✅ vllm-svc 수동Endpoints |

## 견고화 현황
- ✅ **완전성 (brittleness step 1)** — verify_q3 `verify_q3_completeness`, parts.yaml 파생.
- ✅ **verify_fuseki 손-리터럴 (step 2 = 견고화 #3)** — oracle.py 파생. Q1/Q2/Q3/Q5 전부 라이브 ALL PASS, 각 줄 `(parts.yaml 파생)` 표기. parts.yaml 미발견 시 하드 실패.

### 남은 견고화 (실험 본질 아님)
1. **resolve 한글 needle gap** — 빈 needle 거부 / RDB 표시명 검색 폴백. (03 문서 상세)
2. 미커밋 코드 정리 (validate.py·probe_toolcalling.py).
3. (미검) 스케일링 >1000부품 cold·재추론 재측정.

## 다음 세션 권장
지참: `00-overview.md` + 작업 영역 문서.
- 견고화 진입 시: 00 + 03 + 04 + (parts.yaml 실물).
- 완전성 카운트부터가 자연스러움 (parts.yaml 필드 확인 후 즉시 작성 가능).
