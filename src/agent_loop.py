# src/agent_loop.py  (v2.1: check_compatibility 추가, Q4 커버)
#
# 실행: python agent_loop.py "<자연어 질문>"
# 환경변수:
#   VLLM_API_KEY  - vLLM Bearer 키
#   FUSEKI_URL    - Fuseki 엔드포인트 (기본: http://fuseki-svc.default:3030/pc/sparql)
#   CATALOG_DB    - SQLite 경로 (기본: /code/catalog.sqlite)
#   VLLM_BASE_URL - vLLM base URL (기본: http://vllm-svc:8000/v1)

import sys, os, json, re
from openai import OpenAI
from tools import (
    resolve_entity, find_compatible, check_compatibility,
    build_configuration, explain_fact,
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
]

# -- SYSTEM 프롬프트 ----------------------------------------------------------
SYSTEM = """\
너는 PC 부품 호환성 추천 전문가다. 사용자 질문을 분석해 도구를 순서대로 호출하고 결과를 자연어로 종합한다.

[필수 규칙]
1. find_compatible / check_compatibility 호출 전 반드시 resolve_entity 로 IRI 를 먼저 확보한다.
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
_session_iris: set[str] = set()


def _surface_iri(iri: str | None) -> None:
    if iri:
        _session_iris.add(iri)


def _check_iri(iri: str) -> bool:
    return iri in _session_iris


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


# -- 도구 디스패치 ------------------------------------------------------------
def _dispatch(name: str, args: dict) -> dict:
    if name == "resolve_entity":
        result = resolve_entity(**args)
        _surface_iri(result.get("iri"))
        return result

    if name == "find_compatible":
        anchor_iri = args.get("anchor_iri", "")
        if not _check_iri(anchor_iri):
            return {"error": (
                f"anchor_iri {anchor_iri!r} 는 이번 세션에서 resolve_entity 로 "
                "확보되지 않았습니다. 먼저 resolve_entity 를 호출하세요."
            )}
        raw = find_compatible(**args)
        for iri in raw.get("results", []):
            _surface_iri(iri)
        return _enrich(raw)

    if name == "check_compatibility":
        for key in ("iri_a", "iri_b"):
            iri = args.get(key, "")
            if not _check_iri(iri):
                return {"error": (
                    f"{key} {iri!r} 는 이번 세션에서 resolve_entity 로 "
                    "확보되지 않았습니다. 먼저 resolve_entity 를 호출하세요."
                )}
        return check_compatibility(**args)

    if name == "build_configuration":
        anchor_iri = args.get("anchor_iri", "")
        if not _check_iri(anchor_iri):
            return {"error": (
                f"anchor_iri {anchor_iri!r} 는 이번 세션에서 resolve_entity 로 "
                "확보되지 않았습니다. 먼저 resolve_entity 를 호출하세요."
            )}
        raw = build_configuration(**args)
        # 결과 IRI 전부 surface (후속 질문 대비)
        for cfg in raw.get("configurations", []):
            _surface_iri(cfg["mb"]); _surface_iri(cfg["case"])
            for i in cfg["cpu_options"]: _surface_iri(i)
            for i in cfg["ram_options"]: _surface_iri(i)
        for i in raw.get("psu_options", []):
            _surface_iri(i)
        return _enrich_build(raw)

    if name == "explain_fact":
        for key in ("subject_iri", "object_iri"):
            iri = args.get(key, "")
            if not _check_iri(iri):
                return {"error": (
                    f"{key} {iri!r} 는 이번 세션에서 resolve_entity 로 "
                    "확보되지 않았습니다. 먼저 resolve_entity 를 호출하세요."
                )}
        return explain_fact(**args)

    return {"error": f"unknown tool: {name}"}


# -- 메인 루프 ---------------------------------------------------------------
def run(user_query: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user",   "content": user_query},
    ]

    for _ in range(MAX_DEPTH):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            return _strip_think(msg.content or "")

        messages.append(msg)
        for tc in msg.tool_calls:
            args   = json.loads(tc.function.arguments)
            result = _dispatch(tc.function.name, args)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      json.dumps(result, ensure_ascii=False),
            })

    return "[MAX_DEPTH 초과] 루프 한계에 도달했습니다."


# -- 진입점 ------------------------------------------------------------------
if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "7700X 에 맞는 메인보드"
    print(run(query))
