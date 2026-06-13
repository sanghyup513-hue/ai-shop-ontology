# src/agent_loop.py  (v2.1: check_compatibility 추가, Q4 커버)
#
# 실행: python agent_loop.py "<자연어 질문>"
# 환경변수:
#   VLLM_API_KEY  - vLLM Bearer 키
#   FUSEKI_URL    - Fuseki 엔드포인트 (기본: http://fuseki-svc.default:3030/pc/sparql)
#   CATALOG_DB    - SQLite 경로 (기본: /code/catalog.sqlite)
#   VLLM_BASE_URL - vLLM base URL (기본: http://vllm-svc:8000/v1)

import sys, os, json, re, time
from openai import OpenAI
from tools import (
    resolve_entity, find_compatible, check_compatibility,
    build_configuration, explain_fact, get_product_info,
    CATEGORY_ENUM, EXPLAINABLE_PREDS,
)
from rdb_boundary import resolve_display_names

# -- 클라이언트 ---------------------------------------------------------------
client = OpenAI(
    base_url=os.environ.get("VLLM_BASE_URL", "http://vllm-svc:8000/v1"),
    api_key=os.environ.get("VLLM_API_KEY", ""),
)
MODEL     = "Qwen/Qwen3.6-35B-A3B"
MAX_DEPTH = 8

# -- 도구 스키마 (LLM 에 노출) ------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_entity",
            "description": (
                "텍스트(부분문자열)로 부품 IRI 를 조회한다. "
                "find_compatible / check_compatibility 호출 전 반드시 먼저 호출해 IRI 를 확보해야 한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text":     {"type": "string",
                                 "description": "검색할 부품 이름 또는 모델 번호 (부분 매칭)"},
                    "category": {"type": "string",
                                 "enum": sorted(CATEGORY_ENUM)},
                },
                "required": ["text", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_compatible",
            "description": (
                "anchor 부품과 호환되는 target 카테고리 부품 목록을 반환한다.\n"
                "anchor_iri 는 반드시 이번 세션 resolve_entity 결과여야 한다.\n\n"
                "지원 카테고리쌍 (anchor, target):\n"
                "  (cpu, motherboard)/(motherboard, cpu)  -> socketCompatible\n"
                "  (ram, motherboard)/(motherboard, ram)  -> ramCompatible\n"
                "  (motherboard, case)/(case, motherboard)-> boardFitsCase\n"
                "  (psu, gpu)/(gpu, psu)                  -> powerSufficient\n"
                "  (gpu, case)/(case, gpu)                -> gpuFitsCase\n\n"
                "예: '4080 에 맞는 파워' -> anchor=gpu, target=psu\n"
                "예: '4080 이 들어가는 케이스' -> anchor=gpu, target=case"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "anchor_category": {"type": "string", "enum": sorted(CATEGORY_ENUM)},
                    "target_category": {"type": "string", "enum": sorted(CATEGORY_ENUM)},
                    "anchor_iri":      {"type": "string"},
                },
                "required": ["anchor_category", "target_category", "anchor_iri"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_compatibility",
            "description": (
                "두 부품 IRI 간 호환 여부와 사유를 반환한다.\n"
                "두 IRI 모두 이번 세션 resolve_entity 로 확보해야 한다.\n\n"
                "반환 필드:\n"
                "  compatible              bool  - 호환 여부\n"
                "  explicitly_incompatible bool  - 명시적 예외(incompatibleWith) 존재 여부\n"
                "  relations               list  - 발견된 호환 술어 목록\n"
                "  basis_detail            str   - 사유 (반드시 응답에 인용)\n\n"
                "예: 'i5-14600K 와 B760 DDR4 보드 호환되나?'\n"
                "  -> resolve(i5-14600K, cpu) + resolve(B760 DDR4, motherboard)\n"
                "  -> check_compatibility(cpu_iri, mb_iri)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "iri_a": {"type": "string", "description": "첫 번째 부품 IRI"},
                    "iri_b": {"type": "string", "description": "두 번째 부품 IRI"},
                },
                "required": ["iri_a", "iri_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_configuration",
            "description": (
                "GPU 를 앵커로 완전 PC 견적 세트를 조립한다.\n"
                "'견적/구성/빌드/조립/추천' 요청에만 사용. 단순 '가격/재고/평점' 질문에는 쓰지 말 것 → get_product_info.\n"
                "anchor_iri 는 반드시 이번 세션 resolve_entity 로 얻은 GPU IRI 여야 한다.\n\n"
                "반환:\n"
                "  configurations  list - 호환 (보드, 케이스) 쌍 + 각 보드별 CPU/RAM 옵션\n"
                "  psu_options     list - GPU 에 충분한 PSU 목록\n"
                "  pair_count      int  - 보드-케이스 조합 수\n"
                "  basis           list - 사용된 호환 규칙\n\n"
                "예: '4080 으로 PC 견적 짜줘', 'RTX 4080 기반 구성 추천'\n"
                "  -> resolve_entity('4080', 'gpu') -> build_configuration(gpu_iri)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "anchor_iri": {"type": "string", "description": "GPU IRI"},
                },
                "required": ["anchor_iri"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_fact",
            "description": (
                "도출된 호환 사실 1건이 '왜' 성립/미성립하는지 하부 데이터 근거로 설명한다.\n"
                "subject_iri, object_iri 는 이번 세션 resolve_entity/도구 결과로 확보된 IRI 여야 한다.\n\n"
                "predicate 는 다음 중 하나:\n"
                "  socketCompatible / ramCompatible / boardFitsCase /\n"
                "  powerSufficient / gpuFitsCase / incompatibleWith\n\n"
                "반환: holds(bool), premises(전제 목록), basis_detail(한 줄 근거).\n"
                "예: '4080 이 왜 미들타워에 맞아?' -> explain_fact(gpu_iri, 'gpuFitsCase', case_iri)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_iri": {"type": "string", "description": "도출 사실의 주어 IRI"},
                    "predicate":   {"type": "string", "enum": sorted(EXPLAINABLE_PREDS)},
                    "object_iri":  {"type": "string", "description": "도출 사실의 목적어 IRI"},
                },
                "required": ["subject_iri", "predicate", "object_iri"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": (
                "부품의 RDB 상세 정보(가격·재고·평점·SKU·표시명)를 조회한다.\n"
                "가격/재고/평점/판매 여부 등 '카탈로그 사실' 질문에만 사용한다(호환성 아님).\n"
                "주의: '~에 맞는/호환/들어가는/견적/찾아줘' 질문에는 쓰지 말 것 — "
                "그건 find_compatible / check_compatibility / build_configuration 이다.\n"
                "iris 의 각 IRI 는 이번 세션 resolve_entity 로 확보해야 한다.\n\n"
                "반환: products[{iri, category, name, price_krw, stock, sku, rating}], count, missing.\n\n"
                "예: 'RTX 4080 가격 얼마야?' -> resolve_entity('4080','gpu') -> get_product_info([gpu_iri])\n"
                "예: '4080이랑 4090 가격 비교' -> resolve 2회 -> get_product_info([iri1, iri2])"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "iris": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "조회할 부품 IRI 목록 (resolve_entity 결과)",
                    },
                },
                "required": ["iris"],
            },
        },
    },
]

# -- SYSTEM 프롬프트 ----------------------------------------------------------
SYSTEM = """\
너는 PC 부품 쇼핑 도우미다. 호환성 추천뿐 아니라 카탈로그에 있는 가격·재고·평점도 안내한다. 사용자 질문을 분석해 도구를 순서대로 호출하고 결과를 자연어로 종합한다.

[필수 규칙]
0. [도구 선택 — 아래 순서로 판단한다]
   (a) '견적/구성/빌드/조립/추천' → build_configuration (GPU 앵커)
   (b) 'A에 맞는/호환되는/들어가는 B', 'B 찾아줘' 처럼 한 부품 기준 호환 '목록' → find_compatible
   (c) 'A랑 B 호환돼?/되나?', '특정 A에 특정 B 들어가?' 처럼 두 부품의 호환 여부 판정 → check_compatibility
   (d) '왜 A가 B에 맞아/성립해?' → explain_fact
   (e) '얼마/가격/값/비싸/재고/몇 개/평점/SKU' 처럼 특정 부품의 카탈로그 사실 → get_product_info
   - 정확히 도구 하나만 고른다. (a)~(d) 호환/견적 도구를 부르면 그 결과로 답하고 끝낸다 — 사용자가 가격을 직접 묻지 않았으면 뒤이어 get_product_info 를 부르지 말 것.
   - get_product_info 는 오직 (e) 명시적 가격·재고·평점·SKU 질문에만. '맞는/호환/들어가는/견적/찾아줘' 질문엔 절대 금지. 예: "7700X에 맞는 메인보드 찾아줘" → find_compatible (가격 안 물었으니 get_product_info 호출 금지).
   - '들어가' 구분: "<GPU>가 들어가는 케이스 (알려줘)" = 한 부품 기준 케이스 목록 → find_compatible(gpu→case). build_configuration(전체 견적) 아님. / "<특정 케이스>에 <특정 GPU> 들어가?" = 두 부품 호환 판정 → check_compatibility.
   - 가격 질문을 "제공하지 않는다"고 거절하지 말 것 — 가격·재고는 RDB 에 있다. 예: "RTX 4080 가격 얼마야?" → resolve_entity('4080','gpu') → get_product_info([gpu_iri]). 가격은 원(₩) 단위, 재고·평점도 함께 안내.
1. find_compatible / check_compatibility / build_configuration / explain_fact / get_product_info 호출 전 반드시 resolve_entity 로 IRI 를 먼저 확보한다.
2. IRI 는 이번 세션 resolve_entity 결과에서만 사용한다. 직접 만들지 않는다.
3. 결과 종합 시:
   - find_compatible: 응답 첫 문장에 basis(호환 술어)를 명시한다.
     예) "socketCompatible(소켓 호환) 기준으로...", "powerSufficient(전력 충분) 기준으로..."
   - check_compatibility: basis_detail 을 그대로 인용한다.
     * compatible=True  -> "호환됩니다 — <basis_detail>"
     * compatible=False, explicitly_incompatible=True -> "호환되지 않습니다 — <basis_detail>"
     * compatible=False, explicitly_incompatible=False -> "호환 관계가 확인되지 않습니다"
   - build_configuration: basis 의 5규칙을 근거로 명시한다.
     * "gpuFitsCase + boardFitsCase + socketCompatible + ramCompatible + powerSufficient 기준으로..."
     * pair_count 만큼의 보드-케이스 조합을 제시하고, 각 조합의 CPU/RAM 옵션과 호환 PSU 를 표시명으로 안내.
     * configurations 가 비었으면 "조건을 만족하는 보드-케이스 조합 없음", psu_options 가 비었으면 "GPU 전력을 감당할 PSU 없음"을 구분해 답한다.
   - explain_fact: holds 와 basis_detail 을 인용해 '왜' 성립/미성립하는지 전제(premises)와 함께 설명한다.
     * holds=True  -> "성립합니다 — <basis_detail>"
     * holds=False -> "성립하지 않습니다 — <basis_detail>"
4. 부품명은 표시명(display name)만 사용한다. 원시 IRI 를 절대 노출하지 않는다.
5. 결과가 0건이면 "카탈로그에 해당 조건을 만족하는 부품이 없습니다"라고 답한다.
6. 도구 호출 실패(error 필드 있음) 시 사용자에게 오류 내용을 알리고 멈춘다.
"""

# -- 세션 IRI 화이트리스트 (불변식 1) -----------------------------------------
# 세션 상태(IRI 화이트리스트 + 트레이스)는 AgentSession 인스턴스가 소유한다.
# (전역 set 은 장기 구동 HTTP 서버에서 요청 간 누수·동시성 경합을 일으키므로 폐기.)


def _ser_msgs(msgs: list) -> list:
    """GB10 에 실제로 보낸 messages 배열을 직렬화(원문 노출용)."""
    out = []
    for m in msgs:
        if isinstance(m, dict):
            out.append({k: m[k] for k in ("role", "content", "tool_call_id", "name") if k in m})
        else:  # SDK assistant message 객체
            tcs = [{"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                   for tc in (getattr(m, "tool_calls", None) or [])]
            out.append({"role": getattr(m, "role", "assistant"),
                        "content": getattr(m, "content", None),
                        "tool_calls": tcs})
    return out


def _usage(resp) -> dict | None:
    u = getattr(resp, "usage", None)
    if not u:
        return None
    return {"prompt_tokens": getattr(u, "prompt_tokens", None),
            "completion_tokens": getattr(u, "completion_tokens", None),
            "total_tokens": getattr(u, "total_tokens", None)}


def _safe_args(s: str):
    try:
        return json.loads(s)
    except Exception:
        return s


def _strip_think(text: str) -> str:
    """Qwen reasoning 스크래치패드 누수 방어.
    reasoning-parser 가 분리하지 못하고 content 로 샌 경우 제거."""
    if not text:
        return text
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "</think>" in text:          # open 태그만 소실되고 close 만 남은 경우
        text = text.split("</think>")[-1]
    return text.strip()


# -- _enrich: find_compatible 결과 IRI -> 표시명 치환 ------------------------
def _enrich(tool_result: dict) -> dict:
    if "results" not in tool_result:
        return tool_result
    iris = tool_result["results"]
    if not iris:
        return tool_result
    name_map = resolve_display_names(iris)
    enriched = dict(tool_result)
    enriched["results"] = [name_map.get(iri, iri) for iri in iris]
    return enriched


# -- _enrich_build: build_configuration 중첩 IRI -> 표시명 일괄 치환 ----------
def _enrich_build(result: dict) -> dict:
    if "configurations" not in result:
        return result
    iris: set[str] = set(result.get("psu_options", []))
    for cfg in result["configurations"]:
        iris.add(cfg["mb"])
        iris.add(cfg["case"])
        iris.update(cfg["cpu_options"])
        iris.update(cfg["ram_options"])
    if not iris:
        return result
    nm = resolve_display_names(list(iris))
    out = dict(result)
    out["psu_options"] = [nm.get(i, i) for i in result.get("psu_options", [])]
    out["configurations"] = [
        {
            "mb":          nm.get(c["mb"], c["mb"]),
            "case":        nm.get(c["case"], c["case"]),
            "cpu_options": [nm.get(i, i) for i in c["cpu_options"]],
            "ram_options": [nm.get(i, i) for i in c["ram_options"]],
        }
        for c in result["configurations"]
    ]
    return out


# ===========================================================================
# AgentSession — 요청 1건 = 인스턴스 1개 (IRI 화이트리스트 + 추론 트레이스)
# ===========================================================================
class AgentSession:
    """단일 사용자 질의의 에이전트 루프 상태.

    - iris   : 이번 세션 resolve_entity 로 surface 된 IRI 화이트리스트 (불변식 1)
    - trace  : 도구 호출 기록 [{tool, args, result(raw, IRI 보존)}] — 웹 파이프라인 시각화용
    - answer : GB10 최종 종합 자연어
    - turns  : LLM 라운드트립 수

    LLM(GB10) 에는 _enrich 로 표시명 치환한 결과를 넘기지만,
    trace 에는 IRI 가 살아있는 RAW 결과를 저장한다(프런트가 카드를 만든다).
    """

    def __init__(self) -> None:
        self.iris: set[str] = set()
        self.trace: list[dict] = []
        self.answer: str = ""
        self.turns: int = 0
        self.tool_calls: int = 0
        self.llm_ms: int = 0      # GB10 누적 응답시간
        self.tool_ms: int = 0     # 도구(Fuseki+RDB) 누적 시간
        self.llm_io: list[dict] = []   # GB10 요청/응답 원문 (턴별)

    # -- IRI 화이트리스트 -----------------------------------------------------
    def _surface(self, iri: str | None) -> None:
        if iri:
            self.iris.add(iri)

    def _check(self, iri: str) -> bool:
        return iri in self.iris

    def _need_iri(self, key: str, iri: str) -> dict | None:
        if not self._check(iri):
            return {"error": (
                f"{key} {iri!r} 는 이번 세션에서 resolve_entity 로 "
                "확보되지 않았습니다. 먼저 resolve_entity 를 호출하세요."
            )}
        return None

    # -- 도구 디스패치: (llm_view, raw) 반환 ----------------------------------
    # llm_view = LLM 에 넘길 표시명-치환 결과 / raw = 트레이스용 IRI-보존 결과
    def _dispatch(self, name: str, args: dict) -> tuple[dict, dict]:
        if name == "resolve_entity":
            raw = resolve_entity(**args)
            self._surface(raw.get("iri"))
            return raw, raw

        if name == "find_compatible":
            err = self._need_iri("anchor_iri", args.get("anchor_iri", ""))
            if err:
                return err, err
            raw = find_compatible(**args)
            for iri in raw.get("results", []):
                self._surface(iri)
            return _enrich(raw), raw

        if name == "check_compatibility":
            for key in ("iri_a", "iri_b"):
                err = self._need_iri(key, args.get(key, ""))
                if err:
                    return err, err
            raw = check_compatibility(**args)
            return raw, raw

        if name == "build_configuration":
            err = self._need_iri("anchor_iri", args.get("anchor_iri", ""))
            if err:
                return err, err
            raw = build_configuration(**args)
            for cfg in raw.get("configurations", []):
                self._surface(cfg["mb"]); self._surface(cfg["case"])
                for i in cfg["cpu_options"]: self._surface(i)
                for i in cfg["ram_options"]: self._surface(i)
            for i in raw.get("psu_options", []):
                self._surface(i)
            return _enrich_build(raw), raw

        if name == "explain_fact":
            for key in ("subject_iri", "object_iri"):
                err = self._need_iri(key, args.get(key, ""))
                if err:
                    return err, err
            raw = explain_fact(**args)
            return raw, raw

        if name == "get_product_info":
            iris = args.get("iris", [])
            if isinstance(iris, str):
                iris = [iris]
            for iri in iris:
                err = self._need_iri("iris", iri)
                if err:
                    return err, err
            raw = get_product_info(iris)
            return raw, raw

        err = {"error": f"unknown tool: {name}"}
        return err, err

    # -- 메인 루프 ------------------------------------------------------------
    def run(self, user_query: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": user_query},
        ]

        for _ in range(MAX_DEPTH):
            self.turns += 1
            req_messages = _ser_msgs(messages)        # 보내기 직전 스냅샷
            _t0 = time.perf_counter()
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
            self.llm_ms += int((time.perf_counter() - _t0) * 1000)
            msg = resp.choices[0].message

            # -- GB10 요청/응답 원문 캡처 + stdout 로깅(kubectl logs -f 로 실시간) --
            resp_calls = [{"id": tc.id, "name": tc.function.name, "arguments": _safe_args(tc.function.arguments)}
                          for tc in (msg.tool_calls or [])]
            self.llm_io.append({
                "turn":    self.turns,
                "endpoint": f"{client.base_url}",
                "request": {"model": MODEL, "tool_choice": "auto",
                            "tools": [t["function"]["name"] for t in TOOLS],
                            "messages": req_messages},
                "response": {"content": msg.content,
                             "tool_calls": resp_calls,
                             "finish_reason": resp.choices[0].finish_reason,
                             "usage": _usage(resp)},
            })
            print(f"[GB10] turn {self.turns} POST {client.base_url}chat/completions "
                  f"model={MODEL} → finish={resp.choices[0].finish_reason} "
                  f"tool_calls={[c['name'] for c in resp_calls]}", flush=True)
            for c in resp_calls:
                print(f"        ↳ {c['name']}({json.dumps(c['arguments'], ensure_ascii=False)})", flush=True)

            if not msg.tool_calls:
                self.answer = _strip_think(msg.content or "")
                return self.answer

            messages.append(msg)
            for tc in msg.tool_calls:
                self.tool_calls += 1
                args = json.loads(tc.function.arguments)
                _d0 = time.perf_counter()
                llm_view, raw = self._dispatch(tc.function.name, args)
                ms = int((time.perf_counter() - _d0) * 1000)
                self.tool_ms += ms
                self.trace.append({
                    "tool":   tc.function.name,
                    "args":   args,
                    "result": raw,            # IRI 보존본 (프런트 카드용)
                    "ms":     ms,             # 도구 실행(Fuseki/RDB 왕복) 시간
                })
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      json.dumps(llm_view, ensure_ascii=False),
                })

        self.answer = "[MAX_DEPTH 초과] 루프 한계에 도달했습니다."
        return self.answer


# -- 모듈 진입점 (CLI 하위호환) ----------------------------------------------
def run(user_query: str) -> str:
    """CLI/단발 호출용 — 세션 1개를 만들어 최종 자연어만 반환."""
    return AgentSession().run(user_query)


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "7700X 에 맞는 메인보드"
    print(run(query))
