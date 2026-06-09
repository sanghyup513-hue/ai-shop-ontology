# AI 쇼핑몰 — 설계 인계 02: 온톨로지 (v2.2)

## 방식 (B안, 확정)
- **OWL + 추론기.** 사전추론(materialization): 오프라인 추론 → 도출 사실을 그래프에 펼쳐 저장, 런타임은 조회만. 데이터 변경 시 재추론.
- **OWL 프로파일 = RL** — 개체 간 호환 사실 forward-chaining에 적합.
- **트리플스토어/추론기 = Apache Jena Fuseki** (Apache 2.0)
  - Jena 룰 빌트인(ge/le/sum + noValue)으로 수치비교(Q2)·부정예외(Q4)를 구조규칙과 같은 한 메커니즘에서 표현
  - OWL 2 RL이 턴키 아님 → 룰 수작업. 단 현 5규칙은 .rules만으로 동작

## 작업1: 스키마 (확정·검증) — `ontology/pc-schema.ttl`

### 컴포넌트 6종
CPU / Motherboard / GPU / PSU / Case / RAM

### 통제어휘
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
| powerMargin | 수치 리터럴 | GPU별 데이터 |
| lengthMm / maxGpuLengthMm | 수치 리터럴 | GPU / Case |

### 호환 5규칙 — `ontology/pc-compat.rules` (v2.1 수정)
형틀: **4슬롯 = ①타입가드 ②조인 ③예외가드 ④사유술어 materialize**

| 술어 | 패턴 | 방향 | 조건 | 비고 |
|---|---|---|---|---|
| socketCompatible | 공유개체 조인 | CPU ↔ MB | hasSocket 동일 개체 | **v2.1: noValue 가드 제거** |
| ramCompatible | 공유개체 조인 | RAM ↔ MB | hasRAMType == supportsRAMType | 변경 없음 |
| boardFitsCase | 공유개체 조인 | MB → Case | hasFormFactor ∈ supportsFormFactor | 변경 없음 |
| powerSufficient | 수치 빌트인 | PSU → GPU | wattage ≥ recommendedWattage + powerMargin | 변경 없음 |
| gpuFitsCase | 수치 빌트인 | GPU → Case | lengthMm ≤ maxGpuLengthMm | 변경 없음 |

## ⚠️ v2.1 아키텍처 변경 — incompatibleWith 집행 계층 이관

### 변경 전 (v1.x)
- 규칙1(socketCompatible)에 `noValue(?cpu, pc:incompatibleWith, ?mb)` 가드
- 추론 계층이 비호환 쌍을 socketCompatible 미도출로 차단

### 변경 후 (v2.1)
- 규칙1에서 noValue 가드 제거 → socketCompatible은 소켓 물리 일치로만 도출
- **집행 지점 = 앱 계층** (2곳):
  1. `find_compatible`: `FILTER NOT EXISTS { { ?anchor pc:incompatibleWith ?target } UNION { ?target pc:incompatibleWith ?anchor } }`
  2. `check_compatibility`: 쿼리 결과에 incompatibleWith 있으면 `explicitly_incompatible=True` 반환

### 이관 근거
- 규칙 계층 noValue는 "물리 호환 여부"와 "예외 목록 제외"를 혼재 → 관심사 분리
- find_compatible은 "추천"이므로 예외 필터링 적합
- check_compatibility는 "진단"이므로 예외 존재 여부를 투명하게 노출해야 함
- 검증: `find_compatible(i5_14600k→mb)` = [z790_atx, b760_matx] (b760_ddr4 제외 ✅)

## 드러난 설계 사실 (기억할 것)
- **Q3 플랫폼 비고정**: GPU 앵커만으로 build_configuration 호출 시 AM5/LGA1700 양쪽 세트 다 나옴 → 정답. 좁히려면 가격필터 또는 CPU 앵커 추가.
- **Q2 역방향**: powerSufficient는 PSU→GPU 방향으로 저장됨. "이 GPU에 맞는 PSU"는 역방향 조회.
- **resolve 정규화 (v2.1)**: needle·IRI 양쪽을 `REPLACE` 로 `[^a-z0-9]` 제거 후 비교. `i5-14600K`→`i514600k`, `cpu_i5_14600k`→`i514600k` 매칭. 인라인 주입 표면도 `[a-z0-9]`만으로 축소.
  - ⚠️ **한글 needle gap (v2.2)**: 한글만 있는 needle은 제거 후 `""` → `CONTAINS(x,"")` 항상 참 → 임의 항목 `LIMIT 1` 집힘 (무성 오답). 후보 fix는 03 문서 참조. resolve 텍스트검색을 RDB 표시명으로 옮기는 미결 논의와 직결.
