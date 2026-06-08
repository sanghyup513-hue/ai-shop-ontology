# AI 쇼핑몰 — 온톨로지 기반 대화형 커머스

자연어 요청 → LLM 의도해석 → 온톨로지/데이터 질의 → 자연어 추천.
기능 하드코딩 대신 **데이터 + 온톨로지 + LLM**으로 대응하는 아마존 Rufus 스타일 쇼핑몰.

현 단계 목적: 정식 온톨로지(**OWL + 추론기, "B안"**)가 운영 환경에서 실제로 가능한지 **최소 실험 한 바퀴**로 검증.

## 핵심 설계 (확정)
- **OWL 프로파일 = RL** / **트리플스토어·추론기 = Apache Jena Fuseki**
- 사전추론(materialization): 오프라인 추론 → 도출 사실을 그래프에 펼쳐 저장, 런타임은 조회만. 데이터 변경 시 재추론.
- **LLM에 raw SQL/SPARQL 생성 금지** — 파라미터 고정 질의 도구만 노출.
- 호환 = 규칙계산(속성비교+임계값) − 명시적 예외 + 명시적 보강. **규칙은 코드 아닌 데이터.**
- **온톨로지 ↔ RDB 경계**: 추론이 읽는 스펙·정체성 → 온톨로지 / 가격·재고·표시 → RDB. 다리 = IRI 하나.
- 운영 추론 LLM: 외부 GB10 vLLM (Qwen3.6-35B-A3B). **개발(Claude) / 운영(GB10) 분리.**

## 진행 상태
- 작업1 온톨로지 스키마 ✅ / 작업2 SPARQL 도구 인터페이스 ✅
- 작업3 RDB 경계 ✅ / 작업4 에이전트 루프 ✅
- **작업5 데이터 출처·적재 ✅ (이 저장소)** — 단일 출처 → 분기 적재, 불변식 4종, Q1~Q5 확대 재검증 통과

> ⚠️ 모든 검증은 rdflib **드라이런**(룰엔진/RDB를 동등 코드로 대체). 실제 Fuseki·Qwen·클러스터 검증은 미수행.

## 저장소 구조
```
docs/        설계 인계 문서 (단일 출처 누적)
ontology/    pc-schema.ttl, pc-compat.rules  (← v1.5 파일 투입)
data/        parts.yaml = 부품 단일 출처. pc-data.ttl·catalog.sqlite = 빌드 산출물(gitignore)
src/         load.py, verify_task5.py  (← v1.5 코드 4종 투입)
```
`_PUT_V15_FILES_HERE.txt` 안내대로 v1.5 산출물 7종을 넣은 뒤 그 안내 파일은 지우면 됩니다.

## 실행 (드라이런)
```bash
pip install -r requirements.txt
python src/load.py          # parts.yaml → data/pc-data.ttl + data/catalog.sqlite (불변식 체크)
python src/verify_task5.py  # 5규칙 머티 + Q1~Q5 + RDB 후필터 재검증
```

## 검증 질의 5종 (성공조건)
Q1 소켓매칭 · Q2 전력 임계값(≥) · Q3 다중제약 견적 · Q4 예외 우선순위 · Q5 설명가능성.

## 미해결 운영 전제 (실제 환경에서만 검증 가능)
1. vLLM tool calling 동작 + `--tool-call-parser` 값 (안 되면 JSON intent fallback)
2. Fuseki 실측치 (추론지연·재추론시간·SPARQL 응답속도)
3. 클러스터 → GB10 연결 (vllm-svc Service 등록 + 호출 확인)

## 다음
실제 Fuseki 적재 + Qwen tool-calling 검증 → 클러스터 배포. (문서 분리도 1순위 후보)
