# AI 쇼핑몰 — 설계 인계 00: 개요 (v2.3)

> **새 세션 시작 시 이 파일은 항상 지참. 그 세션에서 다룰 파일만 추가로 지참.**
> 변경 이력: …v2.0(find_compatible 10쌍·Q2·Q5 자연어) → v2.1(check_compatibility·Q4 / noValue 제거·incompatibleWith 앱계층 이관 / resolve 정규화) → v2.2(build_configuration·Q3 / explain_fact / verify_q3 건전성 가드 / `<think>` strip / 배포 restart 제거 / resolve 한글 gap 기록) → **v2.3(brittleness 근본수정 완료 — Q3 완전성 + verify_fuseki 손-리터럴 해소 via oracle.py. 기대값 전부 parts.yaml 단일출처 파생·매직넘버 0, 라이브 ALL PASS)**

## 목표
아마존 Rufus 스타일 대화형 AI 쇼핑몰. 자연어 요청 → LLM 의도해석 → 온톨로지/데이터 질의 → 자연어 추천. 기능 하드코딩 대신 데이터 + 온톨로지 + LLM.

**현 단계 목적:** 정식 온톨로지(OWL + 추론기, "B안")가 운영 환경에서 실제로 가능한지 **최소 실험 한 바퀴**로 검증. 편의보다 표현력·추론능력 우선.

## ✅ 실험 결론 (v2.2)
**B안 운영 가능 — 검증 완료.** 5도구 전부 구현·라이브, 검증질의 Q1~Q5 자연어 완주, GB10 vLLM tool-calling 실루프 종단 동작. 남은 항목은 운영화(견고화)이지 실험 성패와 무관.

## 핵심 원칙 (항상 지킬 것)
- **개발(Claude) / 운영(GB10 vLLM) 분리.** 섞지 않는다.
- LLM에 raw SQL/SPARQL 생성 금지 → 파라미터 고정 도구만 노출.
- 딱 떨어지는 처리 = 결정적 코드/쿼리. LLM = 의도해석·종합·설명만.
- 호환 = 규칙계산 − 명시적 예외 + 명시적 보강. **규칙은 코드가 아닌 데이터.**
- 온톨로지 ↔ RDB 경계: 추론이 읽는 스펙/정체성 → 온톨로지 / 가격·재고·표시 → RDB. 다리 = IRI 하나.

## 런타임 구조 (한 줄)
사용자 NL → LLM 의도해석·파라미터 추출 → 고정 SPARQL/SQL 도구 실행(사전추론 사실 위) → LLM 결과 종합·설명.
상세: `03-runtime.md`

## 저장소
`https://github.com/sanghyup513-hue/ai-shop-ontology` (private)
```
docs/        이 문서들
ontology/    pc-schema.ttl · pc-compat.rules(v2.1: rule1 noValue 제거)
data/        parts.yaml  ← pc-data.ttl · catalog.sqlite 는 빌드 산출물(gitignore)
src/         load.py · verify_fuseki.py(v2.3: oracle 파생) · verify_task5.py · verify_q3.py(완전성)
             oracle.py(v2.3: parts.yaml→기대치 파생) · tools.py(5도구 완비) · agent_loop.py(5도구+think strip) · rdb_boundary.py
             [미커밋] validate.py · probe_toolcalling.py
             server.py(웹+API) · rdb_service.py(RDB HTTP)
web/         index.html(메인 UI·토큰/비용 패널) · ontology.html(그래프 시각화)
infra/vagrant/  Vagrantfile · provision/01-common.sh · provision/02-init.sh
k8s/         fuseki-assembler.ttl · fuseki-deploy.yaml(imagePullPolicy:IfNotPresent)
             vllm-svc.yaml · web-deploy.yaml(web+web-svc:30080) · rdb-deploy.yaml(rdb-svc) · probe-vllm.yaml
             (구 agent-deploy.yaml 삭제 — web/rdb 4계층으로 대체)
```
> **배포·실행 명령(복붙)은 `README.md` → 실행 2(클러스터 배포)** 에 정본. 토큰/비용 패널은 `03-runtime.md`.

## 작업 우선순위 (v2.2 기준)
1. ~~온톨로지 스키마~~ ✅  2. ~~SPARQL 도구 인터페이스 (5종)~~ ✅  3. ~~RDB 경계~~ ✅
4. ~~에이전트 루프~~ ✅    5. ~~데이터 출처/적재~~ ✅

**운영 전제 3종 검증:** 전부 ✅

**도구 6종:** resolve_entity ✅ / find_compatible ✅ / check_compatibility ✅ / build_configuration ✅ / explain_fact ✅ / get_product_info ✅ (v2.4, RDB 가격·재고 질의)

**자연어 완주 현황 (Q1~Q5 전부 ✅):**
- [x] Q1 socketCompatible (cpu→mb) ✅ v1.9
- [x] Q2 powerSufficient (gpu→psu 역방향) ✅ v2.0
- [x] Q3 build_configuration (GPU 앵커 → 완전 견적) ✅ **v2.2** — 라이브 통과. 카운트 검증은 건전성+완전성 불변식(verify_q3, v2.3)으로 대체
- [x] Q4 check_compatibility (두 IRI 호환 + 예외 우선순위) ✅ v2.1
- [x] Q5 gpuFitsCase (gpu→case) ✅ v2.0 / explain_fact 로 수치 사유 강화 가능

## 남은 것 (견고화 — 실험 본질 아님)
- ✅ 완전성·verify_fuseki 손-리터럴 (brittleness step 1·2) — v2.3 oracle.py·verify_q3 완전성으로 해소
1. resolve 한글 needle gap — 빈 needle 거부 또는 RDB 표시명 검색 폴백
2. 미커밋 코드 정리 (validate.py·probe_toolcalling.py)
3. (미검) 스케일링 >1000부품 cold·재추론

## 에이전트 자율성 경계
(변경 없음 — v1.9 참조)

## 문서 구성
| 파일 | 내용 | 세션 지참 기준 |
|---|---|---|
| 00-overview.md | **이 파일** — 항상 지참 | 항상 |
| 01-infra.md | 호스트·k8s·GB10·Qwen | 인프라/배포 세션 |
| 02-ontology.md | OWL 방식·스키마·규칙·설계 사실 | 온톨로지 수정 세션 |
| 03-runtime.md | 런타임 구조·SPARQL 도구·RDB 경계·에이전트 루프 | 도구/루프 수정 세션 |
| 04-experiment.md | 산출물·검증질의·검증코드·미해결 견고화 | 실험/검증 세션 |
