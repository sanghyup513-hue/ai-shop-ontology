# AI 쇼핑몰 — 온톨로지 기반 대화형 커머스

자연어 요청 → LLM 의도해석 → 온톨로지/데이터 질의 → 자연어 추천.
기능 하드코딩 대신 **데이터 + 온톨로지 + LLM**으로 대응하는 아마존 Rufus 스타일 쇼핑몰.

정식 온톨로지(**OWL + 추론기, "B안"**)가 운영 환경에서 실제로 가능한지 검증하는 실험 — **현재 클러스터에서 종단 라이브 동작 중**(웹 UI + GB10 추론 + Fuseki 룰추론 + RDB).

## 핵심 설계 (확정)
- **OWL 프로파일 = RL** / **트리플스토어·추론기 = Apache Jena Fuseki**
- 사전추론(materialization): 오프라인 추론 → 도출 사실을 그래프에 펼쳐 저장, 런타임은 조회만. 데이터 변경 시 재추론.
- **LLM에 raw SQL/SPARQL 생성 금지** — 파라미터 고정 질의 도구만 노출.
- 호환 = 규칙계산(속성비교+임계값) − 명시적 예외 + 명시적 보강. **규칙은 코드 아닌 데이터.**
- **온톨로지 ↔ RDB 경계**: 추론이 읽는 스펙·정체성 → 온톨로지 / 가격·재고·표시 → RDB. 다리 = IRI 하나.
- 운영 추론 LLM: 외부 GB10 vLLM (Qwen3.6-35B-A3B). **개발(Claude) / 운영(GB10) 분리.**

## 진행 상태 (v2.4)
- 작업1~5 ✅ — 온톨로지 스키마 · SPARQL 도구 6종 · RDB 경계 · 에이전트 루프 · 단일출처 적재
- **라이브 검증 통과** — Fuseki 실측 추론 + GB10 vLLM tool-calling 실루프 + Q1~Q5 자연어 완주
- **웹 UI 가동** — `http://192.168.56.10:30080/` 4계층 종단(web · rdb-svc · fuseki · GB10)
- **시연용 토큰·비용 패널** — 질의당 입력/출력 토큰 + Claude·GPT 단가 환산 표시

## 4계층 구조
```
브라우저 ──HTTP──▶ web (UI + 에이전트 루프, :30080)
                    ├─HTTP──▶ rdb-svc   (표시명·가격·재고, catalog.sqlite)
                    ├─SPARQL▶ fuseki    (Jena 룰추론, :30030)
                    └─OpenAI▶ vllm-svc ─▶ GB10 vLLM (Qwen3.6-35B-A3B, tailnet)
```
- web/rdb 는 같은 ConfigMap `agent-code`(코드 단일 출처)를 마운트. vllm-svc 는 selector 없는 Service + 수동 Endpoints 로 외부 GB10 을 클러스터 내부로 브리지.

## 저장소 구조
```
docs/        설계 인계 문서 (단일 출처 누적)
ontology/    pc-schema.ttl · pc-compat.rules
data/        parts.yaml = 부품 단일 출처. pc-data.ttl·catalog.sqlite = 빌드 산출물(gitignore)
src/         server.py(웹+API) · agent_loop.py(에이전트 루프·6도구) · tools.py · rdb_boundary.py
             rdb_service.py(RDB HTTP) · oracle.py(기대치 파생) · load.py · verify_*.py
web/         index.html(메인 UI·토큰/비용 패널) · ontology.html(그래프 시각화)
k8s/         web-deploy.yaml · rdb-deploy.yaml · fuseki-deploy.yaml · vllm-svc.yaml · fuseki-assembler.ttl
```

---

## 실행 1 — 로컬 드라이런 (개발 머신, 클러스터 불필요)

룰엔진/RDB 를 rdflib 동등 코드로 대체해 빠르게 검증한다.

```bash
pip install -r requirements.txt
python src/load.py          # parts.yaml → data/pc-data.ttl + data/catalog.sqlite (불변식 체크)
python src/verify_task5.py  # 5규칙 머티 + Q1~Q5 + RDB 후필터 재검증
python src/verify_q3.py     # Q3 건전성+완전성 가드
```

## 실행 2 — 클러스터 배포 (라이브, 단일노드 k8s)

> **전제**: 단일노드 k8s(vm1) + Fuseki + GB10 vLLM 도달 가능. kubeconfig 는 `~/.kube/config-vm1`.
> **반드시 Bash 에서 실행** — PowerShell 파이프는 한글(UTF-8)을 깨뜨린다.

```bash
# 0) kubeconfig
export KUBECONFIG=~/.kube/config-vm1

# 1) 빌드 산출물 생성 (catalog.sqlite — ConfigMap 에 들어감)
python src/load.py

# 2) vLLM API 키 Secret (최초 1회)
kubectl create secret generic vllm-api-key --from-literal=key="<GB10 vLLM API 키>"

# 3) 코드·HTML·데이터 → ConfigMap agent-code  (Bash 파이프 필수)
kubectl create configmap agent-code \
  --from-file=agent_loop.py=src/agent_loop.py \
  --from-file=server.py=src/server.py \
  --from-file=tools.py=src/tools.py \
  --from-file=rdb_boundary.py=src/rdb_boundary.py \
  --from-file=rdb_service.py=src/rdb_service.py \
  --from-file=oracle.py=src/oracle.py \
  --from-file=load.py=src/load.py \
  --from-file=verify_fuseki.py=src/verify_fuseki.py \
  --from-file=verify_q3.py=src/verify_q3.py \
  --from-file=verify_task5.py=src/verify_task5.py \
  --from-file=index.html=web/index.html \
  --from-file=ontology.html=web/ontology.html \
  --from-file=requirements.txt=requirements.txt \
  --from-file=parts.yaml=data/parts.yaml \
  --from-file=catalog.sqlite=data/catalog.sqlite \
  --dry-run=client -o yaml | kubectl apply -f -

# 4) 매니페스트 적용 (최초)
kubectl apply -f k8s/vllm-svc.yaml      # 외부 GB10 → 클러스터 내부 Service 브리지
kubectl apply -f k8s/fuseki-deploy.yaml # Jena 룰추론 (:30030)
kubectl apply -f k8s/rdb-deploy.yaml    # rdb-svc (표시명·가격)
kubectl apply -f k8s/web-deploy.yaml    # web + web-svc (NodePort 30080)

# 접근:  http://192.168.56.10:30080/
```

### 코드 갱신 (재배포)
```bash
export KUBECONFIG=~/.kube/config-vm1
# 위 3) ConfigMap 재생성 명령 다시 실행 후:
#   · server.py / agent_loop.py 등 모듈 변경 → web 재시작 필요 (장기구동 서버는 자동 리로드 안 됨)
#   · web/*.html 만 변경            → 재시작 불필요 (GET 마다 새로 읽음). ~10~40초 내 반영
kubectl rollout restart deploy/web
kubectl rollout status  deploy/web
```

### 라이브 검증
```bash
export KUBECONFIG=~/.kube/config-vm1
POD=$(kubectl get pods -l app=web --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')
kubectl exec "$POD" -c web -- python -c "import urllib.request,json; \
  print(json.load(urllib.request.urlopen('http://localhost:8080/api/health')))"
# /api/health rdb=up · /api/catalog rel_source=rdb-svc · POST /api/ask Q3/Q4 정답
```

---

## 검증 질의 5종 (성공조건)
Q1 소켓매칭 · Q2 전력 임계값(≥) · Q3 다중제약 견적 · Q4 예외 우선순위 · Q5 설명가능성.

## 도구 6종 (LLM 에 노출, 파라미터 고정)
`resolve_entity` · `find_compatible` · `check_compatibility` · `build_configuration` · `explain_fact` · `get_product_info`

## 시연 — 토큰·비용 패널
질의 1건마다 메인 UI 가 표시:
- **입력(내 질문) / 출력(답을 내기까지 소모) / 총 토큰** — 입력은 vLLM `/tokenize` 실측
- **Claude·GPT 단가 환산** — 실제 과금 기준(프롬프트 누계=입력가, 생성 누계=출력가). 단가·환율은 `web/index.html` 상단 `PRICING`/`FX_KRW` 상수에서 수정.

상세 설계·런타임·배포 형상: `docs/`(00 개요 · 01 인프라 · 02 온톨로지 · 03 런타임 · 04 실험).
