# AI 쇼핑몰 프로젝트 — 설계 인계 문서 (v1.5)

> v1.5 (이번 세션): **작업1~4 설계 확정 + 코드로 검증 완료.** 산출물 7종 동봉.
> 이전 결정 누적: v1.4(OWL 프로파일=RL, 스토어=Jena Fuseki) → v1.5(스키마·규칙·도구·RDB경계·에이전트루프).
> ⚠️ 모든 코드 검증은 rdflib 드라이런(룰엔진/RDB를 동등 코드로 대체). 실제 Fuseki·Qwen 검증은 미수행 — 아래 「미해결 운영 전제」 참조.

## 산출물 (이 세션)
- `pc-schema.ttl` — 온톨로지 스키마(TBox + 통제어휘 개체)
- `pc-compat.rules` — 호환 5규칙(Jena 룰 형틀, 4슬롯·2패턴)
- `pc-sample-data.ttl` — 최소실험 샘플 데이터(Q4 예외 1건 심음)
- `validate.py` — 5규칙 머티리얼라이즈 + Q1~Q5 SPARQL 드라이런
- `tools.py` — SPARQL 파라미터 도구 5개 + 가드
- `rdb_boundary.py` — RDB 경계(sqlite) + 가격조인
- `agent_loop.py` — 에이전트 루프(LLM 의도 스텁, 루프 기계장치 실증)

## 목표
- 아마존 Rufus 스타일 대화형 AI 쇼핑몰
- 자연어 요청 → LLM 의도해석 → 온톨로지/데이터 질의 → 자연어 추천
- 기능 하드코딩 대신 데이터+온톨로지+LLM으로 대응

## 이번 단계의 실제 목적 (중요)
- 정식 온톨로지(OWL+추론기, "B안")가 **운영 환경에서 실제로 가능한지** 검증
- 편의보다 표현력·추론능력 우선
- 크게 가지 않고 "최소 실험 한 바퀴" 성공이 1차 목표

## 개발 / 운영 분리
- 개발(설계·코딩): Claude Code + 실제 Claude (서브에이전트: architect/coder/doc-writer/deployer), GB10 개입 안 함
- 운영(서비스 추론): 완성된 앱 → GB10 vLLM 호출

## 인프라 규격 (확정)
### 호스트
- 노트북: 16스레드 / 32GB RAM / 윈도우 + VirtualBox

### 쿠버네티스 클러스터 (단일 노드)
- VM1 (control-plane + worker 겸용, taint 제거)
  - 10 vCPU / 22GB RAM / 120GB 디스크
  - 호스트 잔여: ~6스레드 / ~10GB
- 쿠버네티스 버전: v1.34 / CRI: containerd / CNI: Calico / 설치: kubeadm(바닐라)
- 단일 노드라 control-plane taint 제거하여 워크로드 스케줄 허용
- VM 네트워크: VirtualBox 브리지 어댑터 (GB10과 같은 LAN)

### RAM 배분 가이드 (22GB 내)
- 쿠버네티스 시스템: ~3~4GB / 워크로드(앱+그래프DB+RDB+벡터DB): ~6~8GB / 나머지 헤드룸

### Trade-off (인지)
- 단일 노드라 노드 분산/스케줄링/HA는 검증 불가 → 검증 범위 밖 (목적은 온톨로지+LLM 운영성)
- 실서버 이식 시 멀티노드로 확장, 매니페스트·GB10 연동 그대로 이식

## GB10 (vLLM 전용, 클러스터 외부)
- GB10은 쿠버네티스 노드로 넣지 않음 → 외부 추론 엔드포인트로 취급
- vLLM 이미 실행 중, 사양 충분 → 검증 대상 아닌 "기정사실"
- vLLM: OpenAI 호환 API (http://<GB10_IP>:8000/v1)
- 클러스터에서 ExternalName Service(또는 고정 Endpoints)로 등록 → 앱은 클러스터 내 이름(vllm-svc)으로 호출(이식성)
- 다음 세션 점검: 클러스터→GB10 연결(Service 등록 + 호출 확인)

## 모델
- Qwen/Qwen3.6-35B-A3B (MoE 추정, 활성 ~3B)
  - 양자화 권장 (FP8 ~35GB대 / FP4 ~18-20GB대 + KV캐시)
  - ⚠️ 미확인: tool calling 지원 + vLLM --tool-call-parser 값 → 서빙 시 반드시 검증 (작업4 루프의 핵심 전제)
  - MoE라 decode 부담 적어 GB10 대역폭(273GB/s) 한계에 유리
- 앱 연동: OpenAI SDK base_url을 vllm-svc로 지정

## 런타임 구조 (확정)
사용자 자연어
 → LLM(Qwen): 의도해석 → 도구/파라미터로 매핑
 → 도구 호출: 파라미터화 SPARQL/SQL 실행 (사전추론된 사실 위에서 조회)
 → LLM(Qwen): 결과(basis 포함)를 자연어로 종합·설명
- 무거운 논리추론 = 추론기(오프라인 사전추론), 자연어↔구조화질의 = LLM
- LLM에 raw SQL/SPARQL 직접 생성 금지 → 파라미터만 채움 (작업2에서 인터페이스로 강제)

## 온톨로지 방식 (B안 확정)
- OWL + 추론기. 사전추론(materialization): 오프라인 추론 → 도출 사실을 그래프에 펼쳐 저장, 런타임은 조회만. 데이터 변경 시 재추론.
- **OWL 프로파일 = RL** (개체 간 호환 사실 forward-chaining에 적합. EL은 거대 TBox 분류용이라 부적합)
- **트리플스토어/추론기 = Apache Jena Fuseki** (Apache 2.0 → 운영=수익 서비스까지 무료·이식 제약 0)
  - Jena 룰 빌트인(ge/le/sum + noValue)으로 수치비교(Q2)·부정예외(Q4)를 구조규칙과 같은 한 메커니즘에서 표현 → "규칙=데이터 한 곳에서" 유지, 별도 SHACL 불필요
  - 탈락 기록(재론의 방지): RDFox(무료판 없음·독자 Datalog 이식부담), GraphDB Free(영리 서비스 금지 라이선스 → 쇼핑몰 운영 시 유료 강제)
  - 비용 인지: OWL 2 RL이 턴키 아님 → 룰 수작업. 단 현 5규칙은 조인이 룰에 명시적이라 **OWL RL 룰셋 없이 .rules만으로 동작** (subClassOf/inverse 필요해지면 그때 RL 룰셋 한 겹)
- 호환 = 규칙계산(속성비교+임계값) − 명시적 예외 + 명시적 보강. 규칙은 코드 아닌 "데이터"(새 카테고리=규칙 추가).
- 수치비교(≥,≤)는 Jena 룰 빌트인으로 보강(하이브리드).

## 작업1: 온톨로지 스키마 (확정·검증)
- 컴포넌트 6: CPU/Motherboard/GPU/PSU/Case/RAM
- 규격 값을 **개체로** 모델링(통제어휘): Socket/RAMType/FormFactor → "같은 개체 공유"로 호환추론(문자열 비교 X)
- 객체속성: hasSocket(공유, domain 생략 — RL 오분류 방지), has/supportsRAMType, has/supportsFormFactor, incompatibleWith(symmetric=예외)
- 수치속성(리터럴): wattage/recommendedWattage/powerMargin/lengthMm/maxGpuLengthMm
  - powerMargin은 상수 아닌 GPU별 **데이터**로 둠(규칙=데이터). 없으면 powerSufficient 미도출 → 적재 시 필수 체크
- **호환 5규칙 형틀 (4슬롯: ①타입가드 ②조인 ③예외가드 ④사유술어 materialize)**
  - 패턴1(공유 개체 조인): socketCompatible(CPU↔MB), ramCompatible(RAM↔MB), boardFitsCase(MB↔Case)
  - 패턴2(수치 빌트인): powerSufficient(PSU→GPU, sum+ge), gpuFitsCase(GPU→Case, le)
  - ※ "6종"이 아니라 5관계 (컴포넌트 6종과 혼동했던 표현 정정)
  - 술어 이름 = 호환 사유 → Q5 설명에 사용
- 검증: validate.py 드라이런에서 Q1~Q5 전부 설계대로 통과(소켓 제외·전력 경계 510·예외 override·근거 출력)

## 작업2: SPARQL 파라미터 도구 인터페이스 (확정·검증)
- 도구 5개(고정 파라미터화 쿼리): resolve_entity / find_compatible / check_compatibility / build_configuration / explain_fact
- **불변 규칙:**
  - 모든 가변값은 initBindings(바인딩)로만 주입 → 쿼리 텍스트에 LLM 입력 0
  - IRI 유일 출처 = resolve_entity, 나머지 도구는 미지 IRI 거부(환각 차단)
  - relation은 LLM 비노출 → (anchor,target) 카테고리쌍에서 앱이 자동 도출(정/역 방향 포함)
  - category는 6종 닫힌 enum, 위반 거부
- 검증: tools.py에서 Q1~Q5 도구호출 + 가드 2종(미지IRI·enum) 작동 확인

## 작업3: RDB vs 온톨로지 경계 (확정·검증)
- **판정 규칙: 호환 추론이 읽는 속성 + 정체성(IRI/타입) → 온톨로지. 나머지 전부 → RDB.**
  - 온톨로지: 추론용 스펙·도출술어·예외 (변경 시 재추론)
  - RDB: 가격·재고·SKU·표시명·이미지·평점 (변경 시 재추론 없음)
- **다리 = IRI 하나.** 온톨로지 질의가 IRI 산출 → 앱이 IRI로 RDB 조회.
- 흐름: 온톨로지 우선(하드제약) → RDB 후필터(가격/재고). SQL도 LLM 비노출(고정 SQL + 바인딩, IN 자리수만 구조적).
- 검증: rdb_boundary.py에서 "80만원대 보드" 후필터 동작 + **가격만 변경 시 재머티리얼라이즈 0회** 실증(경계의 실익)
- 운영 이식: sqlite → Postgres 등 교체해도 쿼리 동일

## 작업4: 에이전트 루프 (확정·검증)
- 루프: NL → [LLM 의도해석] → [앱 resolve→도구 실행] → [LLM 종합/설명]
- **불변식 4개:** ①세션에 surface된 IRI만 통과(날조 거부→자기교정) ②raw쿼리 도구 부재 ③도구 결정적·비결정성은 의도/종합에만 ④최대 호출 깊이 상한
- 종합은 basis/basis_detail만 사용 → 근거기반·추적가능(Q5)
- 세션 상태 운반: 후속질문(Q5)이 직전 견적의 IRI 참조
- **vLLM tool calling 미지원 시 fallback:** LLM이 제한 JSON {intent,params} 방출 → 앱이 도구로 매핑. 루프 모양 동일, transport만 교체.
- 검증: agent_loop.py에서 Q1~Q5 + 자기교정(날조 IRI 거부→resolve 재시도→"카탈로그 없음") 통과. 세션 신뢰 IRI 전부 surface 출처 → 환각 0

## 작업5: 데이터 출처/적재 (미착수 — 자율 위임 대상)
- 인계 원칙상 coder 서브에이전트 자율 위임(검증질의 5종 = 기계 판정 성공조건)
- 적재 시 필수 체크: GPU마다 powerMargin 존재, Q4 예외 1건 심기

## 최소 실험 — 검증 질의 5종 (성공조건)
- Q1 소켓 매칭 / Q2 전력 임계값(≥) / Q3 다중제약 견적 / Q4 예외 우선순위 / Q5 설명가능성
- 진단맵: Q1·Q2 실패→기초추론 / Q3 실패→조합·하이브리드 / Q4 실패→표현력 한계 / Q5 실패→LLM↔추론사실 연결
- 성공 기준: LLM→SPARQL→추론사실조회→자연어답변 한 바퀴 완주 + 추론지연·재추론시간·SPARQL응답속도 실측치 확보

## 드러난 설계 사실 (이번 세션, 기억할 것)
- **Q3 플랫폼 비고정:** GPU 앵커만으로 build하면 여러 플랫폼(AM5/LGA1700) 세트 다 나옴 → 정답. 좁히려면 가격필터/CPU앵커 추가
- **Q2 역방향:** powerSufficient는 PSU→GPU. "GPU에 맞는 PSU"는 역방향 — find_compatible이 카테고리쌍으로 방향 자동 택일(고정쿼리 2개 중 선택)
- **resolve 텍스트검색 (미결):** 현재 IRI localname 매칭. 표시명이 RDB에 있으니 RDB 텍스트검색으로 옮기는 게 자연스러움 → 작업4/5에서 결정

## 미해결 운영 전제 (실제 환경에서만 검증 가능)
1. **vLLM tool calling 동작 + --tool-call-parser 값** (작업4 루프 전제) — 안 되면 JSON intent fallback
2. **Fuseki 실측치** (추론지연·재추론시간·SPARQL 응답속도) — 드라이런으론 불가
3. **클러스터→GB10 연결** (vllm-svc Service 등록 + 호출 확인)

## 작업 우선순위 (갱신)
1. ~~온톨로지 스키마~~ ✅ / 2. ~~질의 도구 인터페이스~~ ✅ / 3. ~~RDB 경계~~ ✅ / 4. ~~에이전트 루프~~ ✅
5. 데이터 출처/적재 (자율 위임)
→ 다음 세션 권장: 실제 Fuseki 적재 + Qwen tool-calling 검증(미해결 전제 3개), 그 다음 클러스터 배포

## 에이전트 자율성 경계 (작업 위임 기준)
핵심: "무엇을 만들지"는 사람, "어떻게 작동시킬지"는 에이전트 자율 반복. 자기교정 루프 도는 작업만 위임.
- 자율 위임(성공조건 기계판정 가능): 스키마 코드화, 샘플데이터 적재, SPARQL 작성, 빌드/설치 에러해결, 테스트 있는 코딩. 검증질의 5종 = 성공조건.
- 사람 결정: 설계 결정(OWL프로파일=RL✅, 스토어=Jena✅, 모델링 대상), 주관적 품질
- 승인 게이트: 클러스터 배포·데이터 삭제/재적재 등(deployer는 실행 전 승인, coder는 편집·테스트 자율)
- 안전장치: 명확한 성공조건 / 서브에이전트 권한 차등 / 검증 에이전트 분리(짜는≠검증) / 큰 단계마다 체크포인트

## 문서 분리 계획 (나중에)
- 지금은 단일 문서 누적 유지. 커지면 1회 분리(doc-writer 관리): 00-overview / 01-infra / 02-ontology / 03-runtime / 04-experiment
- 원칙: 00-overview 항상 유지, 새 세션엔 overview + 그 세션 다룰 파일만 지참
- ※ v1.5 기준 문서가 꽤 커짐 → 다음 세션 시작 시 분리 1순위 고려
