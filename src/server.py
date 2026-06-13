# src/server.py — 온톨로지 커머스 웹 서비스 (stdlib only, 무의존)
#
# 한 줄 구조:
#   브라우저 → POST /api/ask → AgentSession(GB10 Qwen 의도해석·도구호출·종합)
#            → tools.py(파라미터화 SPARQL) → Fuseki(룰추론) → RDB(표시명) → JSON
#
# 엔드포인트:
#   GET  /            index.html (옆 패널에 실 추론 트레이스 렌더)
#   GET  /api/catalog parts.yaml → 부품 카드용 카탈로그(스펙+가격+평점)
#   GET  /api/health  헬스체크
#   POST /api/ask     {"q": "..."} → {answer, trace, ...}  (GB10 라이브)
#
# 환경변수: PORT(8080) / PARTS_YAML / + agent_loop 가 읽는 VLLM_*, FUSEKI_URL, CATALOG_DB
#
# 동시요청: ThreadingHTTPServer + 요청별 AgentSession → 세션 상태 격리.

import os
import json
import time
import traceback
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

from agent_loop import AgentSession, MODEL
from tools import _run_sparql_rows, _localname, PC_NS
from rdb_boundary import resolve_display_names

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.environ.get("INDEX_HTML", os.path.join(HERE, "index.html"))
ONTOLOGY_PATH = os.environ.get("ONTOLOGY_HTML", os.path.join(HERE, "ontology.html"))
PARTS_YAML = os.environ.get("PARTS_YAML", os.path.join(HERE, "parts.yaml"))
RDB_URL    = os.environ.get("RDB_URL", "http://rdb-svc:8081").rstrip("/")
FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://fuseki-svc.default:3030/pc/sparql")
VLLM_BASE  = os.environ.get("VLLM_BASE_URL", "http://vllm-svc:8000/v1").rstrip("/")
VLLM_KEY   = os.environ.get("VLLM_API_KEY", "")
PORT = int(os.environ.get("PORT", "8080"))


# -- 서비스 상태 프로브 (데모: 4계층이 실제로 살아있음을 보임) ----------------
def _probe(label: str, fn) -> dict:
    t0 = time.perf_counter()
    try:
        extra = fn() or {}
        return {"name": label, "up": True, "ms": int((time.perf_counter() - t0) * 1000), **extra}
    except Exception as e:  # noqa: BLE001
        return {"name": label, "up": False, "ms": int((time.perf_counter() - t0) * 1000),
                "error": str(e)[:80]}


def _probe_rdb() -> dict:
    with urllib.request.urlopen(f"{RDB_URL}/health", timeout=4) as r:
        d = json.loads(r.read().decode("utf-8"))
    return {"detail": f"{d.get('rows', '?')}행"}


def _probe_fuseki() -> dict:
    q = urllib.parse.urlencode({"query": "ASK {}"})
    req = urllib.request.Request(f"{FUSEKI_URL}?{q}",
                                 headers={"Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()
    return {"detail": "Jena 룰추론"}


def _probe_gb10() -> dict:
    req = urllib.request.Request(f"{VLLM_BASE}/models",
                                 headers={"Authorization": f"Bearer {VLLM_KEY}"})
    with urllib.request.urlopen(req, timeout=6) as r:
        d = json.loads(r.read().decode("utf-8"))
    mid = (d.get("data") or [{}])[0].get("id", "?")
    return {"detail": mid}


def _count_tokens(text: str) -> int | None:
    """vLLM /tokenize 로 텍스트 1건의 정확한 토큰 수. 실패 시 None."""
    if not text:
        return 0
    root = VLLM_BASE[:-3].rstrip("/") if VLLM_BASE.endswith("/v1") else VLLM_BASE
    try:
        body = json.dumps({"model": MODEL, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{root}/tokenize", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {VLLM_KEY}"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8")).get("count")
    except Exception:  # noqa: BLE001
        return None


def token_summary(llm_io: list, query: str) -> dict:
    """질의 1건의 토큰 소비 — '내 질문 한 줄' vs '답을 내기까지 그 외 전부' 프레이밍.

    total = 턴별 (prompt+completion) 누계 = GB10 이 이 질의에 실제로 소비한 총 토큰.
    input  = 사용자 질문만의 토큰 (vLLM /tokenize 로 실측) — 보통 한 줄, 수십 토큰.
    output = total - input = 시스템 프롬프트 + 도구 정의 + N턴 컨텍스트 재전송
             + 도구 결과 + 생성 — 답을 내기까지 소모된 그 외 전부.
    turns/raw_* 는 내부 분해(참고 테이블)용.
    """
    per_turn, sp, sc, st = [], 0, 0, 0
    for t in llm_io:
        u = (t.get("response") or {}).get("usage") or {}
        p = u.get("prompt_tokens") or 0
        c = u.get("completion_tokens") or 0
        tt = u.get("total_tokens") or (p + c)
        sp += p; sc += c; st += tt
        per_turn.append({"turn": t.get("turn"), "prompt": p,
                         "completion": c, "total": tt})
    qtok = _count_tokens(query)
    if qtok is None:
        qtok = 0
    qtok = min(qtok, st)
    return {"input": qtok, "output": st - qtok, "total": st,
            "query_tokens": qtok, "raw_prompt": sp, "raw_completion": sc,
            "turns": per_turn}


def service_status() -> dict:
    return {"services": [
        {"name": "web", "up": True, "ms": 0, "detail": "에이전트 루프"},
        _probe("rdb", _probe_rdb),
        _probe("fuseki", _probe_fuseki),
        _probe("GB10", _probe_gb10),
    ]}


# -- 온톨로지 그래프 (Fuseki 라이브: 기반사실 + 추론엣지 + 예외) ---------------
_PCQ = f"PREFIX pc: <{PC_NS}>\n"
_VOCAB_PREDS = {  # 통제어휘 공유(객체속성) → vtype
    "hasSocket": "socket", "supportsRAMType": "ramtype", "hasRAMType": "ramtype",
    "hasFormFactor": "formfactor", "supportsFormFactor": "formfactor",
}
_INFERRED_PREDS = ["socketCompatible", "ramCompatible", "boardFitsCase",
                   "powerSufficient", "gpuFitsCase"]


def ontology_graph() -> dict:
    # 1) 부품 + 클래스
    parts = _run_sparql_rows(_PCQ + (
        "SELECT ?s ?c WHERE { ?s a ?c . "
        "FILTER(?c IN (pc:CPU,pc:Motherboard,pc:GPU,pc:PSU,pc:Case,pc:RAM)) }"))
    # 2) 기반 사실: 부품 → 통제어휘 객체속성
    asserted = _run_sparql_rows(_PCQ + (
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(?p IN ("
        "pc:hasSocket,pc:supportsRAMType,pc:hasRAMType,pc:hasFormFactor,pc:supportsFormFactor)) }"))
    # 3) 추론된 호환 (추론기 머티리얼라이즈)
    inferred = _run_sparql_rows(_PCQ + (
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(?p IN ("
        "pc:socketCompatible,pc:ramCompatible,pc:boardFitsCase,pc:powerSufficient,pc:gpuFitsCase)) }"))
    # 4) 명시적 예외 (대칭 → 중복제거)
    exc = _run_sparql_rows(_PCQ + "SELECT ?s ?o WHERE { ?s pc:incompatibleWith ?o }")

    nodes: dict[str, dict] = {}
    part_cls: dict[str, str] = {}
    for s, c in parts:
        ln = _localname(s)
        part_cls[ln] = _localname(c)
        nodes[ln] = {"id": ln, "kind": "part", "category": _localname(c), "label": ln}

    edges = []
    for s, p, o in asserted:
        sl, pl, ol = _localname(s), _localname(p), _localname(o)
        nodes.setdefault(ol, {"id": ol, "kind": "vocab", "vtype": _VOCAB_PREDS.get(pl, "vocab"), "label": ol})
        edges.append({"s": sl, "p": pl, "o": ol, "layer": "asserted"})
    for s, p, o in inferred:
        edges.append({"s": _localname(s), "p": _localname(p), "o": _localname(o), "layer": "inferred"})
    seen = set()
    for s, o in exc:
        sl, ol = _localname(s), _localname(o)
        key = frozenset((sl, ol))
        if key in seen:
            continue
        seen.add(key)
        edges.append({"s": sl, "p": "incompatibleWith", "o": ol, "layer": "exception"})

    # 부품 라벨 → RDB 표시명
    full = [PC_NS + ln for ln in part_cls]
    names = resolve_display_names(full)
    for ln in part_cls:
        nodes[ln]["label"] = names.get(PC_NS + ln, ln)

    return {"nodes": list(nodes.values()), "edges": edges,
            "counts": {"parts": len(part_cls), "asserted": sum(1 for e in edges if e["layer"] == "asserted"),
                       "inferred": sum(1 for e in edges if e["layer"] == "inferred"),
                       "exception": sum(1 for e in edges if e["layer"] == "exception")}}


# -- 온톨로지 스펙 (parts.yaml) — web/agent 가 보유하는 추론-측 스펙 view -----
# 관계형 메타(표시명·가격·재고·평점)는 web 이 소유하지 않는다 → rdb 서비스가 권한자.
# /api/catalog 는 [onto 스펙 ⨝ rdb 관계형] 으로 합성한다(경계를 라이브로 시연).
def load_specs() -> dict:
    with open(PARTS_YAML, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    specs = {}
    fallback = {}   # rdb 서비스 장애 시 폴백용 (parts.yaml 의 rdb 필드)
    for p in doc["parts"]:
        o, r = p["onto"], p["rdb"]
        specs[p["iri"]] = {"type": o["type"], "onto": {k: v for k, v in o.items() if k != "type"}}
        fallback[p["iri"]] = {"name": r["display_name"], "price": r["price_krw"],
                              "rating": r["rating"], "stock": r["stock"]}
    return {"base": doc["meta"]["base"], "incompatible": doc.get("incompatible", []),
            "specs": specs, "fallback": fallback}


SPECS = load_specs()


def _rdb_catalog() -> dict | None:
    """rdb 서비스에서 관계형 행 조회 → {iri: {name,price,rating,stock}}. 장애 시 None."""
    try:
        with urllib.request.urlopen(f"{RDB_URL}/catalog", timeout=5) as r:
            rows = json.loads(r.read().decode("utf-8"))
        return {row["iri"]: row for row in rows}
    except Exception:
        return None


def build_catalog() -> dict:
    """onto 스펙(web) ⨝ 관계형(rdb 서비스). rdb 다운이면 parts.yaml 폴백."""
    rel = _rdb_catalog()
    src = "rdb-svc" if rel is not None else "fallback(parts.yaml)"
    if rel is None:
        rel = SPECS["fallback"]
    parts = []
    for iri, sp in SPECS["specs"].items():
        r = rel.get(iri, SPECS["fallback"].get(iri, {}))
        parts.append({
            "iri":    iri,
            "type":   sp["type"],
            "onto":   sp["onto"],
            "name":   r.get("name", iri),
            "price":  r.get("price"),
            "rating": r.get("rating"),
            "stock":  r.get("stock"),
        })
    return {"base": SPECS["base"], "parts": parts,
            "incompatible": SPECS["incompatible"], "rel_source": src}


# -- 핸들러 ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "OntologyCommerce/1.0"

    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                with open(INDEX_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html")
            except FileNotFoundError:
                self._send(404, b"index.html not found", "text/plain")
        elif path in ("/ontology", "/ontology.html"):
            try:
                with open(ONTOLOGY_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html")
            except FileNotFoundError:
                self._send(404, b"ontology.html not found", "text/plain")
        elif path == "/api/graph":
            try:
                self._send(200, json.dumps(ontology_graph(), ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
        elif path == "/api/catalog":
            cat = build_catalog()
            self._send(200, json.dumps(cat, ensure_ascii=False))
        elif path == "/api/health":
            rel = _rdb_catalog()
            self._send(200, json.dumps({
                "ok":      True,
                "parts":   len(SPECS["specs"]),
                "rdb":     "up" if rel is not None else "down",
                "rdb_url": RDB_URL,
            }))
        elif path == "/api/status":
            self._send(200, json.dumps(service_status(), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/ask":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            q = (payload.get("q") or "").strip()
            if not q:
                self._send(400, json.dumps({"ok": False, "error": "빈 질문"}, ensure_ascii=False))
                return

            t0 = time.perf_counter()
            sess = AgentSession()
            answer = sess.run(q)
            elapsed = int((time.perf_counter() - t0) * 1000)
            self._send(200, json.dumps({
                "ok":          True,
                "query":       q,
                "answer":      answer,
                "trace":       sess.trace,
                "turns":       sess.turns,
                "tool_calls":  sess.tool_calls,
                "llm_ms":      sess.llm_ms,
                "tool_ms":     sess.tool_ms,
                "elapsed_ms":  elapsed,
                "llm_io":      sess.llm_io,
                "tokens":      token_summary(sess.llm_io, q),
                "engine":      "GB10 · Qwen3.6-35B-A3B",
            }, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001  — 데모 서버: 어떤 실패도 JSON 으로
            self._send(500, json.dumps({
                "ok":    False,
                "error": str(e),
                "where": traceback.format_exc().splitlines()[-3:],
            }, ensure_ascii=False))

    def log_message(self, fmt: str, *args) -> None:  # 표준 액세스로그 억제
        return


def main() -> None:
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[server] 온톨로지 커머스 listening on :{PORT}  "
          f"(specs {len(SPECS['specs'])} parts, rdb={RDB_URL}, index={INDEX_PATH})",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
