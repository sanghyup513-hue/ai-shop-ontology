"""에이전트 루프 — 03 v1.8 계약 (작업4 슬라이스: resolve_entity + find_compatible).

불변식:
1. 세션에 surface된 IRI만 find_compatible.anchor 로 통과. 날조 IRI 거부 → 자기교정.
2. raw 쿼리 도구 부재 — TOOLS 는 resolve/find 둘뿐.
3. 도구는 결정적, 비결정성은 LLM 의도해석/종합에만.
4. 최대 호출 깊이 상한 (MAX_DEPTH).
"""
import json
import os
import re
import sys

from openai import OpenAI

from rdb_boundary import resolve_display_names
from tools import CATEGORY_TYPE, ToolError, find_compatible, resolve_entity

BASE_URL = os.environ.get("VLLM_BASE", "http://vllm-svc:8000/v1")
API_KEY = os.environ["VLLM_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")
MAX_DEPTH = int(os.environ.get("MAX_DEPTH", "8"))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_entity",
            "description": "제품 텍스트(예: '7700X')를 카탈로그 IRI로 해석. 다른 도구 호출 전 반드시 선행.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string", "enum": sorted(CATEGORY_TYPE)},
                },
                "required": ["text", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_compatible",
            "description": "앵커 IRI와 호환되는 대상 카테고리 목록을 반환.",
            "parameters": {
                "type": "object",
                "properties": {
                    "anchor": {
                        "type": "string",
                        "description": "resolve_entity가 반환한 IRI만 허용",
                    },
                    "target_category": {"type": "string", "enum": sorted(CATEGORY_TYPE)},
                },
                "required": ["anchor", "target_category"],
            },
        },
    },
]

SYSTEM = (
    "당신은 PC 호환성 어시스턴트입니다. 규칙:\n"
    "- 카탈로그의 부품을 칭할 때는 반드시 먼저 resolve_entity로 IRI를 얻어야 합니다.\n"
    "- IRI를 임의로 만들지 마세요. find_compatible의 anchor는 직전 resolve_entity가 "
    "반환한 IRI여야 합니다.\n"
    "- 응답의 첫 문장에 도구가 돌려준 basis 값(예: socketCompatible → '소켓 호환')을 "
    "명시적으로 포함해 근거를 밝히세요.\n"
    "- 응답에는 도구 결과의 results 항목(이미 표시명으로 치환됨)을 그대로 사용하고, "
    "원시 IRI 문자열은 노출하지 마세요."
)

_THINK_RE = re.compile(r".*</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    """vLLM reasoning-parser 켜졌는지 미확인 — </think> 섞이면 뒤만 사용."""
    if not text:
        return text
    m = _THINK_RE.search(text)
    return text[m.end():].lstrip() if m else text


def _enrich(tool_result: dict) -> dict:
    """results 리스트의 IRI를 표시명으로 치환 (basis 등 다른 필드 보존)."""
    iris = tool_result.get("results")
    if not iris:
        return tool_result
    names = resolve_display_names(iris)
    return {**tool_result, "results": [names[i] for i in iris]}


def _dispatch(name: str, args: dict, surfaced: set) -> dict:
    if name == "resolve_entity":
        out = resolve_entity(**args)
        if out.get("status") == "ok":
            surfaced.add(out["iri"])
        return out
    if name == "find_compatible":
        anchor = args.get("anchor", "")
        if anchor not in surfaced:
            return {
                "status": "rejected",
                "reason": "anchor가 세션 surface IRI에 없음 — resolve_entity 선행 필수",
            }
        return find_compatible(**args)
    return {"status": "error", "reason": f"unknown tool {name!r}"}


def run(user_msg: str) -> str:
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    surfaced: set = set()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    for _ in range(MAX_DEPTH):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            content = _strip_think(msg.content or "")
            print(content)
            return content
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"[tool] {tc.function.name}({args})", file=sys.stderr)
            try:
                result = _dispatch(tc.function.name, args, surfaced)
            except ToolError as e:
                result = {"status": "error", "reason": str(e)}
            result = _enrich(result)
            print(f"[result] {result}", file=sys.stderr)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    raise RuntimeError(f"MAX_DEPTH({MAX_DEPTH}) 도달")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: agent_loop.py <자연어 질문>", file=sys.stderr)
        sys.exit(2)
    run(" ".join(sys.argv[1:]))
