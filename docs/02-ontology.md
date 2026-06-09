# AI 쇼핑몰 — 설계 인계 02: 온톨로지 (v1.8)

## 방식 (B안, 확정)
- **OWL + 추론기.** 사전추론(materialization): 오프라인 추론 → 도출 사실을 그래프에 펼쳐 저장, 런타임은 조회만. 데이터 변경 시 재추론.
- **OWL 프로파일 = RL** — 개체 간 호환 사실 forward-chaining에 적합. EL은 거대 TBox 분류용이라 부적합.
- **트리플스토어/추론기 = Apache Jena Fuseki** (Apache 2.0 → 수익 서비스까지 무료·이식 제약 0)
  - Jena 룰 빌트인(ge/le/sum + noValue)으로 수치비교(Q2)·부정예외(Q4)를 구조규칙과 같은 한 메커니즘에서 표현 → "규칙=데이터 한 곳에서" 유지, 별도 SHACL 불필요
  - 탈락 이유: RDFox(무료판 없음·독자 Datalog 이식부담), GraphDB Free(영리 서비스 금지 라이선스)
  - OWL 2 RL이 턴키 아님 → 룰 수작업. 단 현 5규칙은 **OWL RL 룰셋 없이 .rules만으로 동작** (subClassOf/inverse 필요해지면 그때 RL 룰셋 한 겹)

## 작업1: 스키마 (확정·검증) — `ontology/pc-schema.ttl`

### 컴포넌트 6종
CPU / Motherboard / GPU / PSU / Case / RAM

### 통제어휘 (규격 값을 개체로 모델링 → 문자열 비교 X, 개체 공유로 호환추론)
- Socket: AM5, LGA1700
- RAMType: DDR5, DDR4
- FormFactor: ATX, MicroATX, ITX

### 속성
| 속성 | 종류 | 비고 |
|---|---|---|
| hasSocket | 객체 (공유) | domain 생략 — RL 오분류 방지 |
| hasRAMType / supportsRAMType | 객체 (공유) | RAM↔MB |
| hasFormFactor / supportsFormFactor | 객체 (공유) | MB↔Case (Case는 다중값) |
| incompatibleWith | 객체, symmetric | 명시적 예외 |
| wattage / recommendedWattage | 수치 리터럴 | PSU / GPU |
| powerMargin | 수치 리터럴 | GPU별 데이터 (상수 아님 — 규칙=데이터 원칙). 없으면 powerSufficient 미도출 → 적재 시 필수 |
| lengthMm / maxGpuLengthMm | 수치 리터럴 | GPU / Case |

### 호환 5규칙 — `ontology/pc-compat.rules` (v1.8 Fuseki 실측 발화 확인 ✅)
형틀: **4슬롯 = ①타입가드 ②조인 ③예외가드(noValue) ④사유술어 materialize**

| 술어 | 패턴 | 방향 | 조건 | v1.8 실측 |
|---|---|---|---|---|
| socketCompatible | 공유개체 조인 | CPU ↔ MB | hasSocket 동일 개체 (noValue로 incompatibleWith 예외) | ✅ Q1·Q4 |
| ramCompatible | 공유개체 조인 | RAM ↔ MB | hasRAMType == supportsRAMType | ✅ (DDR4×1·DDR5×4) |
| boardFitsCase | 공유개체 조인 | MB → Case | hasFormFactor ∈ supportsFormFactor | ✅ Q3 (8건) |
| powerSufficient | 수치 빌트인 | PSU → GPU | wattage ≥ recommendedWattage + powerMargin (sum+ge) | ✅ Q2 (510 경계 통과) |
| gpuFitsCase | 수치 빌트인 | GPU → Case | lengthMm ≤ maxGpuLengthMm (le) | ✅ Q5 |

※ 술어 이름 = 호환 사유 → Q5 설명에 직접 사용.
※ "6종"이 아니라 5관계 (컴포넌트 6종과 혼동 정정).

**v1.8 실측 구현 메모:**
- Jena GenericRuleReasoner **기본 모드(hybrid)** 에서 noValue·sum·ge·le 4종 모두 발화 확인. 별도 `ja:rulesetMode` 지정 불필요.
- 수치 빌트인 인자 형식은 쉼표 구분: `sum(?a, ?b, ?c)`, `ge(?a, ?b)`, `le(?a, ?b)`. (공백 구분도 일부 버전에서 동작하나 5.1.0에서는 쉼표 형식 사용)

## 드러난 설계 사실 (기억할 것)
- **Q3 플랫폼 비고정**: GPU 앵커만으로 build_configuration 호출 시 AM5/LGA1700 양쪽 세트 다 나옴 → 정답. 좁히려면 가격필터 또는 CPU 앵커 추가.
- **Q2 역방향**: powerSufficient는 PSU→GPU 방향으로 저장됨. "이 GPU에 맞는 PSU"는 역방향 조회 — find_compatible이 카테고리쌍에서 방향을 자동 택일.
- **resolve 텍스트검색 (미결)**: 현재 IRI localname 매칭. 표시명이 RDB에 있으니 RDB 텍스트검색으로 옮기는 게 자연스러움 → 운영 전제 검증 시 결정.
  - v1.7 관찰: tool-calling 프로브 Stage2에서 모델이 "라이젠 7700X"를 `text="7700X"`로 정규화해 `resolve_entity` 호출. 이 부분문자열을 무엇과 매칭할지(localname vs RDB 표시명)가 전제1(Fuseki) 단계에서 실제로 시험될 지점.
  - v1.8 시점: Fuseki 라이브 추론은 통과했으나 resolve_entity는 아직 Fuseki에 연결 안 됨(verify_fuseki.py는 IRI 직접 사용). 통합 한 바퀴 세션에서 결정.
