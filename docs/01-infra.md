# AI 쇼핑몰 — 설계 인계 01: 인프라 (v1.9)

## 호스트
- 노트북: i7-1360P (P코어 4 + E코어 8 = 12코어/16스레드) / 32GB RAM / SSD / Windows + VirtualBox
- ⚠️ **하이브리드코어 주의**: P/E코어 혼합 CPU. VirtualBox에 vCPU를 많이(10) 주면 SMP 부팅이 20초+ 걸리고 게스트 전반이 굼떠짐 → vCPU는 P코어 수(4)에 맞춤. (아래 VM 스펙 참고)

## 쿠버네티스 클러스터 (단일 노드, 실기동 완료 ✅)
- VM1: control-plane + worker 겸용 (taint 제거, 워크로드 스케줄 허용)
  - **4 vCPU** / 22GB RAM / 120GB 디스크  ← vCPU 10→4 하향(하이브리드코어 이슈). 단일노드 검증엔 4로 충분.
  - 호스트 잔여: ~12스레드 / ~10GB
- k8s v1.34 (실측 v1.34.8) / CRI: containerd(SystemdCgroup=true) / CNI: Calico v3.32.0(operator) / 설치: kubeadm(바닐라)
- 포드 CIDR `10.244.0.0/16` (호스트전용 192.168.56.x 와 비충돌. Calico 기본 192.168.0.0/16은 겹쳐서 회피)
- 상태: 컨트롤플레인·calico·coredns 전부 Running, vm1 Ready, Taints 없음.

### VM 네트워크 (확정)
- **호스트전용 고정 IP `192.168.56.10`** 단일 = apiserver advertise-address + kubelet node-ip. 노트북 이동에도 안 변함(내부 가상망).
- **브리지 어댑터 제거** — IP가 네트워크마다 바뀌고 k8s가 쓰지도 않으며, GB10(tailnet)에도 못 닿음.
- GB10 도달은 **VM 안 tailscale**로 (아래 GB10 절). VM tailnet IP = `100.119.172.84` (예시, 디바이스마다 다름).

### Vagrant 재현 (산출물: `infra/vagrant/`)
- 박스: `bento/ubuntu-24.04` (박스 자체엔 문제 없었음 — 느림의 원인은 vCPU였음)
- provider 옵션(타이머/스케줄 안정화, kubeadm 타임아웃 직결):
  - `--paravirtprovider kvm`, `--hpet on`
- 디스크 120GB: `vagrant-disksize` 플러그인 필요
- provisioning: `01-common.sh`(swap off·커널모듈·sysctl·containerd·k8s 패키지) + `02-init.sh`(kubeadm init·Calico·untaint)
- ⚠️ 윈도우에서 받은 `.sh`는 LF 유지(CRLF면 게스트에서 깨짐)

### kubeadm 기동 시 겪은 함정 (재발방지 메모)
1. **`wait-control-plane` 10초 타임아웃 다발** — 첫 기동에 etcd/apiserver가 10초 안에 안 떠서 매번 실패. apiserver는 곧(수십초 뒤) `LISTEN :6443` 됨. 대책: `kubeadm-config.yaml`에 `timeouts.controlPlaneComponentHealthCheck: 4m0s` 박기 + `kubeadm config images pull` 선행. (vCPU 4로 낮춘 뒤로는 init이 자동 완주함)
2. **admin.conf가 NAT IP(10.0.2.15)를 집음** — 일부 init phase가 인증서에 없는 NAT IP로 붙으려다 x509 실패. 대책: `kubectl config set-cluster kubernetes --server=https://192.168.56.10:6443 --kubeconfig=...` 로 server 고정.
3. **RBAC 부트스트랩 미완 시** `kubernetes-admin` Forbidden — `super-admin.conf`로 `clusterrolebinding`(cluster-admin→kubernetes-admin) 직접 생성하면 복구.
4. `cni plugin not initialized` 로그는 Calico 설치 전까지 **정상**(무시).
5. Calico operator 설치 직후 Installation CR 만들 때 CRD 등록 레이스 → `kubectl wait --for=condition=established crd/installations.operator.tigera.io` 선행.
6. **CoreDNS가 systemd-resolved stub(127.0.0.53) 상속** — 파드에서 클러스터외 DNS 해석 불가(vllm-svc 같은 인클러스터명은 됐으나 외부명 실패). 대책: CoreDNS Corefile `forward . 127.0.0.53` → `forward . 10.92.220.71 10.92.220.72`(실 업스트림 DNS 직접 지정). Vagrant 재현 시 재발.

### RAM 배분 가이드 (22GB 내)
- k8s 시스템: ~3~4GB
- 워크로드 (앱 + Fuseki + RDB + 벡터DB): ~6~8GB
- 나머지 헤드룸

### Trade-off (인지)
- 단일 노드라 노드 분산/스케줄링/HA 검증 불가 → 검증 범위 밖 (목적: 온톨로지+LLM 운영성)
- 실서버 이식 시 멀티노드 확장, 매니페스트·GB10 연동 그대로 이식

## Fuseki (클러스터 내, 라이브 추론) — 실측 통과 ✅ (v1.8)
- 이미지: `stain/jena-fuseki` (Fuseki 5.1.0, JVM 21). `apache/jena-fuseki:*` Docker Hub 풀은 현 시점 `insufficient_scope` 실패 → `stain/jena-fuseki` 채택.
- 시작: `fuseki-server --config=/fuseki-config/fuseki-assembler.ttl`
- 어셈블러 구조: `ja:InfModel`(베이스 모델 + GenericRuleReasoner) → `ja:RDFDataset` → `fuseki:Service`. 베이스는 `ja:MemoryModel`로 인메모리, `pc-data.ttl`을 `ja:externalContent`로 적재.
- 규칙 모드: GenericRuleReasoner **기본값(hybrid)** 에서 noValue·sum·ge·le 4종 빌트인 모두 발화 확인. 별도 `ja:rulesetMode` 설정 불필요.
- 매니페스트: `k8s/fuseki-deploy.yaml` (Deployment 1 + NodePort Service 30030) + ConfigMap `fuseki-config` (assembler·rules·data 3파일).
- 리소스: requests 512Mi/500m, limits 2Gi/2cpu. 26부품 기준 충분(JVM 힙 1.5G 설정).
- 접근: `http://192.168.56.10:30030/pc/sparql` (외부) — 클러스터 내부에서는 `http://fuseki-svc.default:3030/pc/sparql`.
- 검증 산출물: `src/verify_fuseki.py` (Q1~Q5 + 타이밍). 상세 04-experiment.

## GB10 (vLLM 전용, 클러스터 외부) — 도달 확인 ✅
- k8s 노드로 넣지 않음 → **외부 추론 엔드포인트**로 취급
- vLLM 실행 중, 사양 충분 → "기정사실"
- 주소: `http://100.82.135.124:8000/v1` (tailnet IP). **API 키 필요**: `Authorization: Bearer <key>` (현재 약한 키 사용 중 → tailnet 내부 한정, 외부노출 금지)
- 도달 경로: VM에 tailscale 설치 → 같은 tailnet 합류 → NAT 너머 DERP/홀펀칭으로 GB10 직통. 브리지 불필요.
  - netcheck: UDP 통, Nearest DERP Tokyo ~40ms.
- `/v1/models` 응답 확인: `id = Qwen/Qwen3.6-35B-A3B`, `max_model_len = 262144`.
- 클러스터 등록 ✅ 완료: `k8s/vllm-svc.yaml` = **헤드리스** Service(`clusterIP: None`, port 8000) + 수동 Endpoints(ip 100.82.135.124). **ExternalName 폐기**(externalName은 DNS-CNAME용, raw IP 부적합). EndpointSlice 자동 미러링. 앱은 `http://vllm-svc:8000/v1`로 호출. (v1 Endpoints는 k8s 1.33+ deprecation 경고 — 차후 EndpointSlice 직접 작성으로 전환 권장)
- 키 봉인: `Secret/vllm-api-key` (key=`key`) → 워크로드 env `VLLM_API_KEY` 주입. **이전의 `GB10_API_KEY` 명칭은 v1.9에 `VLLM_API_KEY`로 통일.**
- 에이전트 가동: `k8s/agent-deploy.yaml` = Deployment(`python:3.12-slim`, `sleep infinity`) + initContainer(`pip install --target=/deps`) + ConfigMap `agent-code`(src/agent_loop.py·tools.py·rdb_boundary.py·requirements.txt + data/catalog.sqlite 동봉, 16KiB로 1MiB cap 한참 아래). 실행: `kubectl exec deploy/agent -- python agent_loop.py "<NL>"`. 코드/데이터 갱신: `kubectl create cm agent-code --from-file=… --dry-run=client -o yaml | kubectl apply -f -; kubectl rollout restart deploy/agent`.

## 모델: Qwen/Qwen3.6-35B-A3B — tool-calling 실측 통과 ✅
- 하이브리드 sparse MoE, 활성 ~3B / 총 35B (멀티모달, 262K 컨텍스트). 2026-04 출시(인계 v1.6 작성 시점 이후라 당시 "미확인"이었음).
- **vLLM serve 플래그 (공식 모델카드):** `--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder`
  - 미확인이던 `--tool-call-parser` 값 = **`qwen3_coder`** 확정.
- **tool calling 실측 결과**(probe_toolcalling.py, VM→GB10):
  - Stage1: 구조화 `tool_calls` 정상 방출 → 파서 동작 확인.
  - Stage2: NL "7700X에 맞는 메인보드" → 모델이 스스로 `resolve_entity(text,category)`부터 호출(루프 불변식과 정합, PASS+).
  - ⇒ **JSON intent fallback 불필요.** (fallback 코드는 안전망으로 보존)
- 관찰: thinking 모델이라 응답 content에 `</think>` 블록이 섞임 → 앱 종합 단계에서 reasoning 분리 필요. `--reasoning-parser qwen3`로 분리 가능(서빙 플래그 확인 권장).
- 양자화 권장: FP8 ~35GB대 / FP4 ~18~20GB대 + KV캐시 (GB10 단일 장치라 공식예시의 `--tensor-parallel-size 8`은 해당 없음)
- 앱 연동: OpenAI SDK `base_url = vllm-svc`, `api_key = <GB10 키>`
