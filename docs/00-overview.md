# AI 쇼핑몰 — 설계 인계 00: 개요 (v1.7)

> **새 세션 시작 시 이 파일은 항상 지참. 그 세션에서 다룰 파일만 추가로 지참.**
> 변경 이력: v1.4(OWL RL·Jena Fuseki 확정) → v1.5(작업1~4 설계+코드 검증) → v1.6(작업5 완료·문서 5분할·GitHub 저장소 개설) → v1.7(전제2·3 실측 통과: GB10 tool-calling 동작·도달 확인, k8s 단일노드 클러스터 실제 기동)

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
src/         load.py · verify_task5.py · validate.py · tools.py · rdb_boundary.py · agent_loop.py · probe_toolcalling.py(v1.7)
infra/vagrant/  Vagrantfile · provision/01-common.sh · provision/02-init.sh  (v1.7, k8s 단일노드)
```

## 작업 우선순위 (v1.6 기준)
1. ~~온톨로지 스키마~~ ✅  2. ~~SPARQL 도구 인터페이스~~ ✅  3. ~~RDB 경계~~ ✅
4. ~~에이전트 루프~~ ✅    5. ~~데이터 출처/적재~~ ✅

**운영 전제 3종 검증 (실제 환경):**
- [ ] **전제1 Fuseki 실측** (추론지연·재추론시간·SPARQL 응답속도) — **미완, 다음 작업**
- [x] **전제2 Qwen tool-calling** ✅ 실측통과. parser=`qwen3_coder`, reasoning-parser=`qwen3`. Stage1(구조)·Stage2(루프-정합) 둘 다 PASS. fallback 불필요. (상세 01·04)
- [x] **전제3 GB10 도달** ✅ 통과. tailnet 경유로 VM→GB10 `/v1/models` 응답·tool-call 왕복 확인. **남은 것: vllm-svc Service 등록**(ExternalName, 설계완료·실행만). (상세 01)

**부수 성과:** k8s 단일노드 클러스터를 실제로 기동 완료(VM1, Calico Ready). 기동 중 드러난 호스트 의존 이슈(vCPU·타이머·kubeadm 타임아웃)는 01-infra에 기록.

→ 전제1까지 통과 후: 클러스터 배포. 세션 지참 파일 = 00-overview + 01-infra + 04-experiment.

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
