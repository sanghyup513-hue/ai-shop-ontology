# AI 쇼핑몰 — 설계 인계 00: 개요 (v2.0)

> **새 세션 시작 시 이 파일은 항상 지참. 그 세션에서 다룰 파일만 추가로 지참.**
> 변경 이력: …v1.9(전제3 마무리·통합 한 바퀴 Q1·agent Deployment 실가동·IRI→표시명 룩업) → **v2.0(find_compatible 10쌍 실가동·Q2(gpu→psu 역방향)·Q5(gpu→case 정방향) 자연어 완주 / CoreDNS upstream 8.8.8.8 전환·Fuseki imagePullPolicy:IfNotPresent 안정화)**

## 목표
아마존 Rufus 스타일 대화형 AI 쇼핑몰. 자연어 요청 → LLM 의도해석 → 온톨로지/데이터 질의 → 자연어 추천. 기능 하드코딩 대신 데이터 + 온톨로지 + LLM.

**현 단계 목적:** 정식 온톨로지(OWL + 추론기, "B안")가 운영 환경에서 실제로 가능한지 **최소 실험 한 바퀴**로 검증. 편의보다 표현력·추론능력 우선.

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
ontology/    pc-schema.ttl · pc-compat.rules
data/        parts.yaml  ← pc-data.ttl · catalog.sqlite 는 빌드 산출물(gitignore)
src/         load.py · verify_fuseki.py · verify_task5.py
             tools.py(v2.0: 10쌍) · agent_loop.py(v2.0: 10쌍+Q2/Q5 SYSTEM) · rdb_boundary.py
             [미커밋] validate.py · probe_toolcalling.py
infra/vagrant/  Vagrantfile · provision/01-common.sh · provision/02-init.sh
k8s/         fuseki-assembler.ttl · fuseki-deploy.yaml(imagePullPolicy:IfNotPresent)
             vllm-svc.yaml · agent-deploy.yaml · probe-vllm.yaml
```

## 작업 우선순위 (v2.0 기준)
1. ~~온톨로지 스키마~~ ✅  2. ~~SPARQL 도구 인터페이스~~ ✅(2종 완료, 3종 미구현)  3. ~~RDB 경계~~ ✅
4. ~~에이전트 루프~~ ✅    5. ~~데이터 출처/적재~~ ✅

**운영 전제 3종 검증:** 전부 ✅ (상세 v1.9 이력 참조)

**자연어 완주 현황:**
- [x] Q1 socketCompatible (cpu→mb) ✅ v1.9
- [x] Q2 powerSufficient (gpu→psu 역방향) ✅ **v2.0** — 4건 + basis 노출 + 표시명 치환
- [x] Q5 gpuFitsCase (gpu→case 정방향) ✅ **v2.0** — 2건 + basis 노출
- [ ] Q3 build_configuration (GPU 앵커 → 완전 견적)
- [ ] Q4 check_compatibility (두 IRI 간 호환 여부 + 예외 우선순위)

**다음:** check_compatibility 구현 → Q4 자연어 완주. 지참 = 00 + 03 + 04.

## 에이전트 자율성 경계
(변경 없음 — v1.9 참조)

## 문서 구성
| 파일 | 내용 | 세션 지참 기준 |
|---|---|---|
| 00-overview.md | **이 파일** — 항상 지참 | 항상 |
| 01-infra.md | 호스트·k8s·GB10·Qwen | 인프라/배포 세션 |
| 02-ontology.md | OWL 방식·스키마·규칙·설계 사실 | 온톨로지 수정 세션 |
| 03-runtime.md | 런타임 구조·SPARQL 도구·RDB 경계·에이전트 루프 | 도구/루프 수정 세션 |
| 04-experiment.md | 산출물·검증질의·작업5·미해결 전제 | 실험/검증 세션 |
