"""Fuseki 파라미터화 도구 — 03 v1.8 계약 (resolve_entity, find_compatible 슬라이스).

불변:
- 가변값은 initBindings로만 주입 — 쿼리 텍스트에 LLM 입력 0.
- IRI 유일 출처 = resolve_entity.
- relation은 LLM 비노출 — (anchor 카테고리, target_category)에서 앱이 도출.
- category enum 6종 위반 즉시 거부.
"""
import os
import re

from rdflib import Graph, URIRef, Literal
from rdflib.plugins.stores.sparqlstore import SPARQLStore

FUSEKI_SPARQL = os.environ.get("FUSEKI_SPARQL", "http://fuseki-svc:3030/pc/sparql")
PC = "http://example.org/pc#"

CATEGORY_TYPE = {
    "cpu": "CPU",
    "motherboard": "Motherboard",
    "gpu": "GPU",
    "psu": "PSU",
    "case": "Case",
    "ram": "RAM",
}

LOCALNAME_PREFIX_TO_CATEGORY = {
    "cpu_": "cpu",
    "mb_": "motherboard",
    "gpu_": "gpu",
    "psu_": "psu",
    "case_": "case",
    "ram_": "ram",
}

# (anchor_category, target_category) → (relation_localname, forward)
# forward=True: ?anchor :rel ?t / forward=False: ?t :rel ?anchor
COMPAT_RELATION = {
    ("cpu", "motherboard"): ("socketCompatible", True),
}

_TEXT_RE = re.compile(r"^[a-z0-9_]+$")
_LOCALNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class ToolError(Exception):
    pass


def _graph():
    return Graph(store=SPARQLStore(query_endpoint=FUSEKI_SPARQL))


def _check_category(value, field):
    if value not in CATEGORY_TYPE:
        raise ToolError(f"{field} not in enum {sorted(CATEGORY_TYPE)}: {value!r}")


def _anchor_localname(iri):
    if not iri.startswith(PC):
        raise ToolError(f"anchor IRI 가 pc: prefix 아님: {iri!r}")
    ln = iri[len(PC):]
    if not _LOCALNAME_RE.match(ln):
        raise ToolError(f"anchor localname 형식 위반: {ln!r}")
    return ln


def _category_of(iri):
    ln = _anchor_localname(iri)
    for prefix, cat in LOCALNAME_PREFIX_TO_CATEGORY.items():
        if ln.startswith(prefix):
            return cat
    raise ToolError(f"anchor localname 으로 카테고리 도출 불가: {ln!r}")


def resolve_entity(text: str, category: str) -> dict:
    _check_category(category, "category")
    norm = (text or "").strip().lower()
    if not _TEXT_RE.match(norm):
        return {"status": "not_found", "reason": "text 정규화 실패"}
    type_ln = CATEGORY_TYPE[category]
    # needle은 ^[a-z0-9_]+$ 게이트 통과 후 인라인. rdflib SPARQLStore의 initBindings가
    # FILTER 표현식 내부 변수까지는 전파 안 되는 제약 회피. 정규식이 SPARQL 메타문자를
    # 차단하므로 LLM 입력의 쿼리 영향은 0 (initBindings 의미 동등).
    q = (
        f'PREFIX pc: <{PC}> '
        f'SELECT ?iri WHERE {{ '
        f'  ?iri a pc:{type_ln} . '
        f'  FILTER(CONTAINS(LCASE(STR(?iri)), "{norm}")) '
        f'}} ORDER BY ?iri'
    )
    rows = list(_graph().query(q))
    iris = [str(r.iri) for r in rows]
    if not iris:
        return {"status": "not_found"}
    if len(iris) > 1:
        return {"status": "ambiguous", "candidates": iris}
    return {"status": "ok", "iri": iris[0]}


def find_compatible(anchor: str, target_category: str) -> dict:
    _check_category(target_category, "target_category")
    anchor_cat = _category_of(anchor)
    key = (anchor_cat, target_category)
    if key not in COMPAT_RELATION:
        raise ToolError(f"호환 관계 미지원 (이번 슬라이스): {key}")
    rel_ln, forward = COMPAT_RELATION[key]
    pattern = (
        f"?anchor pc:{rel_ln} ?t" if forward
        else f"?t pc:{rel_ln} ?anchor"
    )
    q = (
        f"PREFIX pc: <{PC}> "
        f"SELECT ?t WHERE {{ {pattern} . }} ORDER BY ?t"
    )
    rows = list(_graph().query(q, initBindings={"anchor": URIRef(anchor)}))
    return {"results": [str(r.t) for r in rows], "basis": rel_ln}
