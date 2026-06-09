# AI 쇼핑몰 — 설계 인계 00: 개요 (v1.9)

> **새 세션 시작 시 이 파일은 항상 지참. 그 세션에서 다룰 파일만 추가로 지참.**
> 변경 이력: v1.4(OWL RL·Jena Fuseki 확정) → v1.5(작업1~4 설계+코드 검증) → v1.6(작업5 완료·문서 5분할·GitHub 저장소 개설) → v1.7(전제2·3 실측 통과: GB10 tool-calling 동작·도달 확인, k8s 단일노드 클러스터 실제 기동) → v1.8(**전제1 Fuseki 실측 통과**: 클러스터 파드에서 5규칙 라이브 발화 + Q1~Q5 정합 + 타이밍 cold 150ms / warm 39ms) → v1.9(전제3 마무리: vllm-svc 수동Endpoints 등록·파드도달 ✅ / 통합 한 바퀴 Q1 경로 실인프라 완주: NL→LLM(qwen3_coder)→resolve→find_compatible→자연어 종합 / 레포-문서 src 불일치 정정 / **agent Deployment 실가동**: ConfigMap(src+catalog.sqlite) + initContainer pip + Secret `vllm-api-key` / **IRI→표시명 룩업 연결**: rdb_boundary 실재화·`_enrich` 도구결과 후처리·SYSTEM 강화로 basis 명시·표시명 노출 검증 통과)

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
ontology/    pc-schema.ttl · pc-compat.rules  (v1.5 산출물, 직접 투입)
data/        parts.yaml (단일 출처)  ← pc-data.ttl · catalog.sqlite 는 빌드 산출물(gitignore)
src/         [실재] load.py · verify_fuseki.py(env전환) · verify_task5.py · tools.py(5도구중 2) · agent_loop.py(2도구 루프 + _enrich 표시명) · rdb_boundary.py(resolve_display_names)
             [미커밋·placeholder] validate.py · probe_toolcalling.py — git 히스토리 전무. probe는 v1.7에 실행됐으나 코드 미반입. _PUT_V15_FILES_HERE.txt 가 자리표시.
infra/vagrant/  Vagrantfile · provision/01-common.sh · provision/02-init.sh  (v1.7, k8s 단일노드)
k8s/         fuseki-assembler.ttl · fuseki-deploy.yaml · vllm-svc.yaml(수동Endpoints) · agent-deploy.yaml(신규, ConfigMap+initContainer+Secret 패턴) · probe-vllm.yaml(디버그 보존)
```

## 작업 우선순위 (v1.8 기준)
1. ~~온톨로지 스키마~~ ✅  2. ~~SPARQL 도구 인터페이스~~ ✅  3. ~~RDB 경계~~ ✅
4. ~~에이전트 루프~~ ✅    5. ~~데이터 출처/적재~~ ✅

**운영 전제 3종 검증 (실제 환경):**
- [x] **전제1 Fuseki 실측** ✅ 통과. Jena 5.1.0 + GenericRuleReasoner(hybrid 기본). 클러스터 파드에서 5규칙 라이브 발화·Q1~Q5 드라이런 결과와 일치·noValue/sum/ge/le 빌트인 4종 작동. 타이밍: cold 150ms / warm 39ms / 추론비용 110ms (26부품 규모). (상세 04)
- [x] **전제2 Qwen tool-calling** ✅ 실측통과. parser=`qwen3_coder`, reasoning-parser=`qwen3`. Stage1(구조)·Stage2(루프-정합) 둘 다 PASS. fallback 불필요. (상세 01·04)
- [x] **전제3 GB10 도달·등록** ✅ 완료. vllm-svc = 셀렉터없는 Service + 수동 Endpoints(raw tailnet IP 100.82.135.124:8000). 임시파드 curl→/v1/models 응답 확인 = 파드 egress→tailnet 라우팅 증명(Calico masq 우려 해소). (상세 01)

**부수 성과:** k8s 단일노드 클러스터를 실제로 기동 완료(VM1, Calico Ready). 기동 중 드러난 호스트 의존 이슈(vCPU·타이머·kubeadm 타임아웃)는 01-infra에 기록.

→ 전제 3종 ✅ + **통합 한 바퀴 Q1 경로 실인프라 완주** ✅ (NL "7700X 메인보드"→ resolve_entity→ surface IRI→ find_compatible(socketCompatible)→ 2건→ `_enrich`로 IRI→표시명 치환→ basis 인용 자연어 종합. 불변식1·MAX_DEPTH·relation비노출·표시명만 노출 전수 통과). 다음: **Q2~Q5 자연어 확장 + 나머지 3도구(check/build/explain) + `(gpu,motherboard)` 등 호환관계 확장**. 지참 = 00 + 03 + 04.

## 에이전트 자율성 경계
핵심: "무엇을 만들지"는 사람, "어떻게 작동시킬지"는 에이전트 자율 반복.
- **자율 위임** (성공조건 기계판정 가능): 스키마 코드화·샘플 적재·SPARQL 작성·빌드/설치 에러해결·테스트 있는 코딩. 검증질의 5종 = 기계 판정 성공조건.
- **사람 결정**: 설계 결정(OWL 프로파일=RL ✅, 스토어=Jena ✅, 모델링 대상), 주관적 품질.
- **승인 게이트**: 클러스터 배포·데이터 삭제/재적재 (deployer는 실행 전 승인, coder는 편집·테스트 자율).
- 안전장치: 명확한 성공조건 / 서브에이전트 권한 차등 / 검증 에이전트 분리(짜는 ≠ 검증) / 큰 단계마다 체크포인트.

## 문서 구성
| 파일 | 내용 | 세션 지참 기준 |
|---|---|---|
| 00-overview.md | **이 파일** — 항상 지참 | 항상 |
| 01-infra.md | 호스트·k8s·GB10·Qwen | 인프라/배포 세션 |
| 02-ontology.md | OWL 방식·스키마·규칙·설계 사실 | 온톨로지 수정 세션 |
| 03-runtime.md | 런타임 구조·SPARQL 도구·RDB 경계·에이전트 루프 | 도구/루프 수정 세션 |
| 04-experiment.md | 산출물·검증질의·작업5·미해결 전제 | 실험/검증 세션 |
