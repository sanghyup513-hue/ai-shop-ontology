# src/tools.py  (v2.1: check_compatibility 추가)
#
# PC_NS = ontology/pc-schema.ttl base namespace 와 반드시 일치
# 설계 원칙
#   - 모든 가변값 IRI: 인라인 주입 (whitelist 선검증, 메타문자 거부)
#   - text: LCASE CONTAINS + _TEXT_SAFE 검증 후 인라인
#   - category: 6종 닫힌 enum, 위반 즉시 거부

import os, re
from collections import defaultdict
from rdflib import Graph, Namespace
from rdflib.plugins.stores.sparqlstore import SPARQLStore

# -- 설정 -------------------------------------------------------------------
FUSEKI_ENDPOINT = os.environ.get(
    "FUSEKI_URL", "http://fuseki-svc.default:3030/pc/sparql"
)
PC_NS = "http://example.org/pc#"   # <- pc-schema.ttl base namespace 로 교체
PC    = Namespace(PC_NS)

# -- 카테고리 / 클래스 매핑 --------------------------------------------------
CATEGORY_ENUM: frozenset[str] = frozenset(
    {"cpu", "motherboard", "gpu", "psu", "case", "ram"}
)

CATEGORY_CLASS: dict[str, str] = {
    "cpu":         "CPU",
    "motherboard": "Motherboard",
    "gpu":         "GPU",
    "psu":         "PSU",
    "case":        "Case",
    "ram":         "RAM",
}

# -- 호환 관계 맵 (find_compatible) ------------------------------------------
# (anchor_cat, target_cat) -> (relation_localname, is_forward)
#   is_forward=True  : SELECT ?target WHERE { <anchor> pc:rel ?target }
#   is_forward=False : SELECT ?target WHERE { ?target pc:rel <anchor> }
RELATION_MAP: dict[tuple[str, str], tuple[str, bool]] = {
    ("cpu",         "motherboard"): ("socketCompatible",  True),
    ("motherboard", "cpu"):         ("socketCompatible",  False),
    ("ram",         "motherboard"): ("ramCompatible",     True),
    ("motherboard", "ram"):         ("ramCompatible",     False),
    ("motherboard", "case"):        ("boardFitsCase",     True),
    ("case",        "motherboard"): ("boardFitsCase",     False),
    ("psu",         "gpu"):         ("powerSufficient",   True),
    ("gpu",         "psu"):         ("powerSufficient",   False),
    ("gpu",         "case"):        ("gpuFitsCase",       True),
    ("case",        "gpu"):         ("gpuFitsCase",       False),
}

# -- 호환/비호환 관계 상수 (check_compatibility) -----------------------------
KNOWN_COMPAT_RELS: frozenset[str] = frozenset({
    "socketCompatible", "ramCompatible", "boardFitsCase",
    "powerSufficient",  "gpuFitsCase",
})
INCOMPAT_REL = "incompatibleWith"

RELATION_DESC: dict[str, str] = {
    "socketCompatible": "소켓 호환",
    "ramCompatible":    "RAM 타입 호환",
    "boardFitsCase":    "폼팩터 호환",
    "powerSufficient":  "전력 충분",
    "gpuFitsCase":      "GPU 길이 적합",
    "incompatibleWith": "명시적 비호환",
}

# -- 검증 패턴 ---------------------------------------------------------------
_IRI_RE    = re.compile(r'^' + re.escape(PC_NS) + r'[A-Za-z0-9_]+$')
_TEXT_SAFE = re.compile(r'^[A-Za-z0-9\uAC00-\uD7A3\s_\-\.]+$')


def _validate_iri(iri: str) -> bool:
    return bool(_IRI_RE.match(iri))


def _localname(uri: str) -> str:
    """URI localname: '#' 구분자 우선, 없으면 마지막 '/' 이후."""
    return uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]


# -- SPARQL 실행 헬퍼 --------------------------------------------------------
def _run_sparql(sparql: str) -> list[str]:
    store = SPARQLStore(FUSEKI_ENDPOINT)
    g     = Graph(store=store)
    return [str(row[0]) for row in g.query(sparql)]


def _run_sparql_rows(sparql: str) -> list[tuple[str, ...]]:
    """다중 컬럼 SELECT -> 각 행을 문자열 튜플로 (SELECT 변수 순서 보존)."""
    store = SPARQLStore(FUSEKI_ENDPOINT)
    g     = Graph(store=store)
    return [tuple(str(v) for v in row) for row in g.query(sparql)]


# -- 쿼리 템플릿 -------------------------------------------------------------
# needle/IRI 양쪽을 [a-z0-9] 로 정규화 후 CONTAINS — 하이픈/공백/언더스코어 차이 흡수.
# (예: "i5-14600K" → "i514600k" 가 "...cpu_i5_14600k" → "...cpui514600k" 에 매칭)
_RESOLVE_TMPL = (
    "PREFIX pc: <{ns}>\n"
    "SELECT ?iri WHERE {{\n"
    "  ?iri a pc:{cls} .\n"
    '  FILTER(CONTAINS(REPLACE(LCASE(STR(?iri)), "[^a-z0-9]", ""), "{needle}"))\n'
    "}}\nLIMIT 1\n"
)

# incompatibleWith 명시 예외는 추론 계층이 아니라 여기(앱 계층)에서 제외한다.
# (규칙1의 noValue 가드 제거로 socketCompatible 이 예외 쌍에도 도출되므로 필수)
_INCOMPAT_GUARD = (
    "  FILTER NOT EXISTS {{ <{anchor}> pc:incompatibleWith ?target }}\n"
    "  FILTER NOT EXISTS {{ ?target pc:incompatibleWith <{anchor}> }}\n"
)

_COMPAT_FWD = (
    "PREFIX pc: <{ns}>\n"
    "SELECT ?target WHERE {{\n"
    "  <{anchor}> pc:{relation} ?target .\n"
    + _INCOMPAT_GUARD +
    "}}\n"
)

_COMPAT_REV = (
    "PREFIX pc: <{ns}>\n"
    "SELECT ?target WHERE {{\n"
    "  ?target pc:{relation} <{anchor}> .\n"
    + _INCOMPAT_GUARD +
    "}}\n"
)

_COMPAT_CHECK = (
    "PREFIX pc: <{ns}>\n"
    "SELECT ?rel WHERE {{\n"
    "  {{ <{iri_a}> ?rel <{iri_b}> }}\n"
    "  UNION\n"
    "  {{ <{iri_b}> ?rel <{iri_a}> }}\n"
    "  FILTER(?rel IN (\n"
    "    pc:socketCompatible, pc:ramCompatible, pc:boardFitsCase,\n"
    "    pc:powerSufficient,  pc:gpuFitsCase,  pc:incompatibleWith\n"
    "  ))\n"
    "}}\n"
)

# build_configuration: 구조 조인 (case/mb/cpu/ram) + cpu<->mb 예외 필터
# PSU 는 GPU 에만 종속 -> 별도 쿼리(inner-join 붕괴 방지)
_BUILD_STRUCT = (
    "PREFIX pc: <{ns}>\n"
    "SELECT DISTINCT ?mb ?case ?cpu ?ram WHERE {{\n"
    "  <{gpu}> pc:gpuFitsCase     ?case .\n"
    "  ?mb     pc:boardFitsCase    ?case .\n"
    "  ?cpu    pc:socketCompatible ?mb .\n"
    "  ?ram    pc:ramCompatible    ?mb .\n"
    "  FILTER NOT EXISTS {{\n"
    "    {{ ?cpu pc:incompatibleWith ?mb }} UNION {{ ?mb pc:incompatibleWith ?cpu }}\n"
    "  }}\n"
    "}}\n"
)

_BUILD_PSU = (
    "PREFIX pc: <{ns}>\n"
    "SELECT DISTINCT ?psu WHERE {{\n"
    "  ?psu pc:powerSufficient <{gpu}> .\n"
    "}}\n"
)


# ===========================================================================
# 도구 1: resolve_entity
# ===========================================================================
def resolve_entity(text: str, category: str) -> dict:
    """
    텍스트(부분문자열) -> IRI. 2-arm 매칭.
      arm1 (온톨로지): IRI localname CONTAINS (정규화, 대소문자 무시) — 모델조각/약칭에 강함.
      arm2 (RDB):     표시명 부분일치 (유일할 때만) — 전체 표시명("Intel Core i5-14600K")·한글("미들타워")에 강함.
    arm1 이 빗나가면 arm2 로 폴백. arm2 다중매칭은 모호(ambiguous)로 거부해 무성 오답 방지.
    반환: {"iri": ..., "text", "category", "via": ontology|rdb|miss, "ambiguous"?: bool}
    """
    if category not in CATEGORY_ENUM:
        return {"error": f"unknown category: {category!r}. must be one of {sorted(CATEGORY_ENUM)}"}
    if not _TEXT_SAFE.match(text):
        return {"error": "text contains unsafe characters"}

    klass = CATEGORY_CLASS[category]

    # arm1: 온톨로지 localname CONTAINS. 비영숫자 제거 → needle 은 [a-z0-9] (인라인 안전).
    needle = re.sub(r"[^a-z0-9]", "", text.lower())
    if needle:
        rows = _run_sparql(_RESOLVE_TMPL.format(ns=PC_NS, cls=klass, needle=needle))
        if rows:
            return {"iri": rows[0], "text": text, "category": category, "via": "ontology"}

    # arm2: RDB 표시명 부분일치 (유일할 때만). 전체 표시명/한글 표시어 대응.
    from rdb_boundary import search_by_name
    matches = search_by_name(text, klass)
    if len(matches) == 1:
        return {"iri": PC_NS + matches[0], "text": text, "category": category, "via": "rdb"}

    return {"iri": None, "text": text, "category": category,
            "via": "miss", "ambiguous": len(matches) > 1}


# ===========================================================================
# 도구 2: find_compatible
# ===========================================================================
def find_compatible(anchor_category: str, target_category: str, anchor_iri: str) -> dict:
    """
    anchor 와 호환되는 target 카테고리 부품 목록 반환.
    지원 쌍: cpu<->mb, ram<->mb, mb<->case, psu<->gpu, gpu<->case
    반환: {"results": [...], "basis": "socketCompatible", "count": 2, ...}
    """
    for lbl, val in [("anchor_category", anchor_category), ("target_category", target_category)]:
        if val not in CATEGORY_ENUM:
            return {"error": f"unknown {lbl}: {val!r}"}

    key = (anchor_category, target_category)
    if key not in RELATION_MAP:
        supported = ", ".join(f"({a},{t})" for a, t in sorted(RELATION_MAP))
        return {"error": f"unsupported pair {key}. supported: {supported}"}

    if not _validate_iri(anchor_iri):
        return {"error": f"invalid anchor IRI: {anchor_iri!r}"}

    relation, is_forward = RELATION_MAP[key]
    tmpl   = _COMPAT_FWD if is_forward else _COMPAT_REV
    sparql = tmpl.format(ns=PC_NS, anchor=anchor_iri, relation=relation)

    rows = _run_sparql(sparql)
    return {
        "results":         rows,
        "basis":           relation,
        "anchor":          anchor_iri,
        "anchor_category": anchor_category,
        "target_category": target_category,
        "count":           len(rows),
    }


# ===========================================================================
# 도구 3: check_compatibility
# ===========================================================================
def check_compatibility(iri_a: str, iri_b: str) -> dict:
    """
    두 부품 IRI 간 호환 여부 + 사유 반환.

    반환 필드:
      compatible              bool  - 호환 관계 존재 AND 명시 비호환 없음
      relations               list  - 발견된 호환 술어 목록
      explicitly_incompatible bool  - incompatibleWith 트리플 존재 여부
      basis_detail            str   - 사람이 읽을 사유 (LLM 종합에 사용)

    Q4 시나리오 (i5_14600k <-> b760_ddr4):
      소켓 LGA1700 공유 -> socketCompatible 미도출 (noValue guard)
      incompatibleWith 명시 트리플 존재 -> explicitly_incompatible=True, compatible=False
    """
    for lbl, iri in [("iri_a", iri_a), ("iri_b", iri_b)]:
        if not _validate_iri(iri):
            return {"error": f"invalid {lbl}: {iri!r}"}

    sparql = _COMPAT_CHECK.format(ns=PC_NS, iri_a=iri_a, iri_b=iri_b)
    rows   = _run_sparql(sparql)

    found         = {_localname(r) for r in rows}
    expl_incompat = INCOMPAT_REL in found
    compat_rels   = sorted(found & KNOWN_COMPAT_RELS)
    compatible    = bool(compat_rels) and not expl_incompat

    if expl_incompat:
        detail = "incompatibleWith(명시적 비호환) - 예외 우선"
        if compat_rels:
            detail += " / 소켓은 일치하나 예외 등록됨"
    elif compat_rels:
        detail = " / ".join(f"{r}({RELATION_DESC.get(r, r)})" for r in compat_rels)
    else:
        detail = "관계 없음 (다른 카테고리이거나 호환 규칙 미해당)"

    return {
        "compatible":              compatible,
        "relations":               compat_rels,
        "explicitly_incompatible": expl_incompat,
        "basis_detail":            detail,
    }


# ===========================================================================
# 도구 4: build_configuration
# ===========================================================================
def build_configuration(anchor_iri: str) -> dict:
    """
    GPU 앵커 -> 완전 견적 세트 (5규칙 체인).

    구조 제약 (단일 조인):
      gpuFitsCase(GPU, Case) + boardFitsCase(MB, Case)
      + socketCompatible(CPU, MB) + ramCompatible(RAM, MB)
      + cpu<->mb incompatibleWith 예외 제외 (추천 도구이므로 필터)
    PSU: powerSufficient(PSU, GPU) -- GPU 에만 종속, 별도 쿼리.

    반환:
      anchor          str   - GPU IRI
      configurations  list  - [{mb, case, cpu_options, ram_options}, ...]
                              cpu/ram 은 해당 MB 종속이라 쌍별로 묶음
      psu_options     list  - GPU 에 충분한 PSU (플랫)
      basis           list  - 사용된 5규칙 술어
      pair_count      int   - (mb, case) 고유 쌍 수 (Q3 검증 기준)

    참고: configurations 가 비어도 psu_options 는 채워질 수 있음(역도 성립).
          "구성 가능"이려면 configurations 와 psu_options 둘 다 비어있지 않아야 함.
    """
    if not _validate_iri(anchor_iri):
        return {"error": f"invalid anchor IRI: {anchor_iri!r}"}

    struct_rows = _run_sparql_rows(_BUILD_STRUCT.format(ns=PC_NS, gpu=anchor_iri))
    psu_rows    = _run_sparql(_BUILD_PSU.format(ns=PC_NS, gpu=anchor_iri))

    # (mb, case) 쌍별 cpu/ram 집계
    agg: dict[tuple[str, str], dict[str, set]] = defaultdict(
        lambda: {"cpu": set(), "ram": set()}
    )
    for mb, case, cpu, ram in struct_rows:
        agg[(mb, case)]["cpu"].add(cpu)
        agg[(mb, case)]["ram"].add(ram)

    configurations = [
        {
            "mb":          mb,
            "case":        case,
            "cpu_options": sorted(v["cpu"]),
            "ram_options": sorted(v["ram"]),
        }
        for (mb, case), v in sorted(agg.items())
    ]

    return {
        "anchor":         anchor_iri,
        "configurations": configurations,
        "psu_options":    sorted(psu_rows),
        "basis": ["gpuFitsCase", "boardFitsCase", "socketCompatible",
                  "ramCompatible", "powerSufficient"],
        "pair_count":     len(configurations),
    }


# ===========================================================================
# 도구 6: get_product_info — RDB 상세(가격·재고·평점·SKU) 조회
# ===========================================================================
# 온톨로지(호환 추론)가 아니라 RDB 경계(rdb-svc)를 친다. 가격/재고/평점 질문 전용.
# IRI 는 resolve_entity 로 확보된 것이어야 함(세션 화이트리스트는 agent_loop 에서 검사).
def get_product_info(iris) -> dict:
    """부품 IRI(1개 또는 목록) → RDB 상세. {products:[{iri,category,name,price_krw,stock,sku,rating}], count, missing}."""
    if isinstance(iris, str):
        iris = [iris]
    if not isinstance(iris, list) or not iris:
        return {"error": "iris must be a non-empty list of IRIs"}
    bad = [i for i in iris if not _validate_iri(i)]
    if bad:
        return {"error": f"invalid IRI(s): {bad}"}

    from rdb_boundary import product_info as _rdb_product_info
    info = _rdb_product_info(iris)
    products = [{"iri": i, **info[i]} for i in iris if i in info]
    missing = [i for i in iris if i not in info]
    return {"products": products, "count": len(products), "missing": missing}


# ===========================================================================
# 도구 5: explain_fact
# ===========================================================================
# 도출 술어 1건의 "왜"를 설명한다. 추론기가 펼친 사실(예: gpuFitsCase)을 받아,
# 그 규칙을 발화시킨 하부 데이터 속성(예: lengthMm <= maxGpuLengthMm)을 되짚는다.
# build_configuration / find_compatible 의 basis 를 사람이 읽을 근거로 전개 (Q5 강화).
EXPLAINABLE_PREDS: frozenset[str] = KNOWN_COMPAT_RELS | {INCOMPAT_REL}


def explain_fact(subject_iri: str, predicate: str, object_iri: str) -> dict:
    """
    도출 사실 <subject> pc:<predicate> <object> 의 성립 여부 + 근거(전제) 반환.

    반환 필드:
      holds         bool  - 해당 트리플이 그래프에 존재하는지
      premises      list  - 규칙을 발화시킨 하부 데이터 속성(사람이 읽을 문자열)
      basis_detail  str   - 한 줄 종합 근거 (LLM 인용용)

    지원 술어 = 5호환규칙 + incompatibleWith.
    """
    for lbl, iri in [("subject_iri", subject_iri), ("object_iri", object_iri)]:
        if not _validate_iri(iri):
            return {"error": f"invalid {lbl}: {iri!r}"}
    if predicate not in EXPLAINABLE_PREDS:
        return {"error": (
            f"unknown predicate: {predicate!r}. "
            f"must be one of {sorted(EXPLAINABLE_PREDS)}"
        )}

    holds = bool(_run_sparql(
        f"PREFIX pc: <{PC_NS}>\n"
        f"SELECT (1 AS ?x) WHERE {{ <{subject_iri}> pc:{predicate} <{object_iri}> }} LIMIT 1"
    ))

    premises: list[str] = []
    if predicate == "socketCompatible":
        rows = _run_sparql_rows(
            f"PREFIX pc: <{PC_NS}>\nSELECT ?sock WHERE {{ "
            f"<{subject_iri}> pc:hasSocket ?sock . <{object_iri}> pc:hasSocket ?sock }}"
        )
        if rows:
            premises.append(f"공유 소켓 {_localname(rows[0][0])} (CPU.hasSocket == MB.hasSocket)")
    elif predicate == "ramCompatible":
        rows = _run_sparql_rows(
            f"PREFIX pc: <{PC_NS}>\nSELECT ?t WHERE {{ "
            f"<{subject_iri}> pc:hasRAMType ?t . <{object_iri}> pc:supportsRAMType ?t }}"
        )
        if rows:
            premises.append(f"RAM 타입 {_localname(rows[0][0])} 일치 (RAM.hasRAMType ∈ MB.supportsRAMType)")
    elif predicate == "boardFitsCase":
        rows = _run_sparql_rows(
            f"PREFIX pc: <{PC_NS}>\nSELECT ?ff WHERE {{ "
            f"<{subject_iri}> pc:hasFormFactor ?ff . <{object_iri}> pc:supportsFormFactor ?ff }}"
        )
        if rows:
            premises.append(f"폼팩터 {_localname(rows[0][0])} 수용 (MB.hasFormFactor ∈ Case.supportsFormFactor)")
    elif predicate == "powerSufficient":
        rows = _run_sparql_rows(
            f"PREFIX pc: <{PC_NS}>\nSELECT ?w ?rw ?m WHERE {{ "
            f"<{subject_iri}> pc:wattage ?w . "
            f"<{object_iri}> pc:recommendedWattage ?rw . <{object_iri}> pc:powerMargin ?m }}"
        )
        if rows:
            w, rw, m = rows[0]
            premises.append(
                f"PSU {w}W ≥ 권장 {rw}W + 마진 {m}W = {int(rw) + int(m)}W (wattage ≥ recWatt + powerMargin)"
            )
    elif predicate == "gpuFitsCase":
        rows = _run_sparql_rows(
            f"PREFIX pc: <{PC_NS}>\nSELECT ?len ?max WHERE {{ "
            f"<{subject_iri}> pc:lengthMm ?len . <{object_iri}> pc:maxGpuLengthMm ?max }}"
        )
        if rows:
            ln, mx = rows[0]
            premises.append(f"GPU 길이 {ln}mm ≤ 케이스 최대 {mx}mm (lengthMm ≤ maxGpuLengthMm)")
    elif predicate == "incompatibleWith":
        premises.append("명시적 비호환(incompatibleWith) — 소켓 등 물리 일치와 무관하게 예외 등록됨")

    rel_desc = RELATION_DESC.get(predicate, predicate)
    if holds:
        basis = f"{predicate}({rel_desc}) 성립 — " + (
            "; ".join(premises) if premises else "전제 데이터 조회 결과 없음"
        )
    else:
        basis = f"{predicate}({rel_desc}) 미성립 — 해당 트리플이 그래프에 없음"

    return {
        "subject":      subject_iri,
        "predicate":    predicate,
        "object":       object_iri,
        "holds":        holds,
        "premises":     premises,
        "basis_detail": basis,
    }
