# AI 쇼핑몰 — 설계 인계 01: 인프라 (v2.0)

## 호스트
- 노트북: i7-1360P (P코어 4 + E코어 8 = 12코어/16스레드) / 32GB RAM / SSD / Windows + VirtualBox
- ⚠️ **하이브리드코어 주의**: P/E코어 혼합 CPU. VirtualBox에 vCPU를 많이(10) 주면 SMP 부팅이 20초+ 걸리고 게스트 전반이 굼떠짐 → vCPU는 P코어 수(4)에 맞춤.

## 쿠버네티스 클러스터 (단일 노드, 실기동 완료 ✅)
- VM1: control-plane + worker 겸용 (taint 제거, 워크로드 스케줄 허용)
  - **4 vCPU** / 22GB RAM / 120GB 디스크
  - 호스트 잔여: ~12스레드 / ~10GB
- k8s v1.34 (실측 v1.34.8) / CRI: containerd(SystemdCgroup=true) / CNI: Calico v3.32.0(operator) / 설치: kubeadm(바닐라)
- 포드 CIDR `10.244.0.0/16`
- 상태: 컨트롤플레인·calico·coredns 전부 Running, vm1 Ready, Taints 없음.

### VM 네트워크 (확정)
- **호스트전용 고정 IP `192.168.56.10`** — apiserver advertise-address + kubelet node-ip.
- **브리지 어댑터 제거** — IP가 네트워크마다 바뀌고 k8s가 쓰지도 않음.
- GB10 도달은 **VM 안 tailscale**로. VM tailnet IP = `100.119.172.84`

### Vagrant 재현 (산출물: `infra/vagrant/`)
- 박스: `bento/ubuntu-24.04`
- provider 옵션: `--paravirtprovider kvm`, `--hpet on`
- 디스크 120GB: `vagrant-disksize` 플러그인 필요
- provisioning: `01-common.sh` + `02-init.sh`
- ⚠️ 윈도우에서 받은 `.sh`는 LF 유지(CRLF면 게스트에서 깨짐)

### kubeadm 기동 시 겪은 함정 (재발방지 메모)
1. **`wait-control-plane` 10초 타임아웃 다발** → `kubeadm-config.yaml`에 `timeouts.controlPlaneComponentHealthCheck: 4m0s` + `kubeadm config images pull` 선행.
2. **admin.conf가 NAT IP(10.0.2.15)를 집음** → `kubectl config set-cluster kubernetes --server=https://192.168.56.10:6443`로 server 고정.
3. **RBAC 부트스트랩 미완 시** → `super-admin.conf`로 `clusterrolebinding` 직접 생성.
4. `cni plugin not initialized` 로그는 Calico 설치 전까지 정상(무시).
5. Calico operator 설치 직후 CRD 등록 레이스 → `kubectl wait --for=condition=established crd/installations.operator.tigera.io` 선행.
6. **CoreDNS upstream (v2.0 갱신)**: ~~`forward . 127.0.0.53`~~ → ~~`forward . 10.92.220.71 10.92.220.72`~~ → **`forward . 8.8.8.8 8.8.4.4`**
   - 사유: `.71/.72` 사내 upstream 이 같은 날 rotate 돼 죽음 — Corefile 은 그대로인데 DNS 해석만 실패. 공용 8.8.8.8 로 전환해 내부 rotation 면역. Vagrant 재현 시 Corefile 에 8.8.8.8 직접 기입 권장.

### RAM 배분 가이드 (22GB 내)
- k8s 시스템: ~3~4GB
- 워크로드 (앱 + Fuseki + RDB + 벡터DB): ~6~8GB
- 나머지 헤드룸

## Fuseki (클러스터 내, 라이브 추론) — 실측 통과 ✅
- 이미지: `stain/jena-fuseki` (Fuseki 5.1.0, JVM 21)
- **`imagePullPolicy: IfNotPresent`** ← v2.0 추가. 캐시 이미지로 기동(재시작 0). Docker Hub `apache/jena-fuseki:*` `insufficient_scope` 이슈 회피.
- 시작: `fuseki-server --config=/fuseki-config/fuseki-assembler.ttl`
- 어셈블러 구조: `ja:InfModel`(베이스 + GenericRuleReasoner) → `ja:RDFDataset` → `fuseki:Service`. 베이스는 `ja:MemoryModel`, `pc-data.ttl` `ja:externalContent` 적재.
- 규칙 모드: GenericRuleReasoner **기본값(hybrid)**. noValue·sum·ge·le 4종 발화 확인.
- 매니페스트: `k8s/fuseki-deploy.yaml` (Deployment 1 + NodePort 30030) + ConfigMap `fuseki-config`.
- 리소스: requests 512Mi/500m, limits 2Gi/2cpu.
- 접근: `http://192.168.56.10:30030/pc/sparql` (외부) / `http://fuseki-svc.default:3030/pc/sparql` (클러스터 내)
- 검증: `src/verify_fuseki.py` (Q1~Q5 + 타이밍). cold 150ms / warm 39ms / 추론비용 110ms.

## GB10 (vLLM 전용, 클러스터 외부) — 도달 확인 ✅
- 주소: `http://100.82.135.124:8000/v1` (tailnet IP). **API 키 필요**: `Authorization: Bearer <key>`.
- `/v1/models` 응답: `id = Qwen/Qwen3.6-35B-A3B`, `max_model_len = 262144`.
- 클러스터 등록: `k8s/vllm-svc.yaml` = 헤드리스 Service + 수동 Endpoints(ip 100.82.135.124). 앱은 `http://vllm-svc:8000/v1`로 호출.
- 키 봉인: `Secret/vllm-api-key` → env `VLLM_API_KEY`.
- 에이전트: `k8s/agent-deploy.yaml` = Deployment + initContainer(pip) + ConfigMap `agent-code` + Secret.
  갱신: `kubectl create cm agent-code --from-file=… --dry-run=client -o yaml | kubectl apply -f -; kubectl rollout restart deploy/agent`.

## 모델: Qwen/Qwen3.6-35B-A3B — tool-calling 실측 통과 ✅
- **vLLM serve 플래그:** `--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder`
- tool calling 실측: Stage1(구조)·Stage2(루프-정합) 통과. fallback 불필요(코드 보존).
- thinking 모델: `--reasoning-parser qwen3`로 `</think>` 분리 작동.
