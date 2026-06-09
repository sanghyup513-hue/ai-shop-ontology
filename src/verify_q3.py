# src/verify_q3.py
#
# Q3 build_configuration 소건전성(soundness) 불변식.
# verify_fuseki.py 에 병합하거나 단독 실행 가능.
#
# 설계 의도 (04 문서 brittleness 근본수정의 1단계):
#   카운트 == 리터럴 비교를 폐기. 매직넘버 0개.
#   "반환된 구성이 전부 유효한가"(soundness)만 검사 -> 데이터 추가에 불변.
#   완전성(completeness, "유효한 게 전부 반환됐나")은 parts.yaml 파생으로 별도 작성.

import os, sys
import yaml
from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import build_configuration, resolve_entity, PC_NS, FUSEKI_ENDPOINT


def _ln(iri: str) -> str:
    return iri.split("#")[-1] if "#" in iri else iri.split("/")[-1]


def _ask(sparql: str) -> bool:
    g   = Graph(store=SPARQLStore(FUSEKI_ENDPOINT))
    res = g.query(sparql)
    try:
        return bool(res.askAnswer)
    except AttributeError:
        return bool(res)


def _ask_rel(subj: str, rel: str, obj: str) -> bool:
    return _ask(f"PREFIX pc: <{PC_NS}>\nASK {{ <{subj}> pc:{rel} <{obj}> }}")


def _ask_incompat(a: str, b: str) -> bool:
    return _ask(
        f"PREFIX pc: <{PC_NS}>\n"
        f"ASK {{ {{ <{a}> pc:incompatibleWith <{b}> }} "
        f"UNION {{ <{b}> pc:incompatibleWith <{a}> }} }}"
    )


def verify_q3_soundness(anchor_iri: str) -> bool:
    """build_configuration(anchor) 반환물의 모든 항목이 Fuseki 사실과 일치하는지 검사."""
    result = build_configuration(anchor_iri)
    if "error" in result:
        print(f"FAIL  build_configuration error: {result['error']}")
        return False

    configs = result["configurations"]
    psus    = result["psu_options"]
    ok      = True

    # 불변식 0: pair_count 일관성 + (mb, case) 쌍 distinct
    pairs = [(c["mb"], c["case"]) for c in configs]
    if result["pair_count"] != len(configs):
        print(f"FAIL  pair_count({result['pair_count']}) != len(configurations)({len(configs)})")
        ok = False
    if len(set(pairs)) != len(pairs):
        print("FAIL  중복 (mb, case) 쌍 존재")
        ok = False

    # 불변식 1: 각 쌍의 구조 제약 (gpuFitsCase + boardFitsCase)
    for c in configs:
        if not _ask_rel(anchor_iri, "gpuFitsCase", c["case"]):
            print(f"FAIL  gpuFitsCase 불성립: anchor -> {_ln(c['case'])}")
            ok = False
        if not _ask_rel(c["mb"], "boardFitsCase", c["case"]):
            print(f"FAIL  boardFitsCase 불성립: {_ln(c['mb'])} -> {_ln(c['case'])}")
            ok = False

    # 불변식 2 (Q4 회귀 가드): cpu_option 중 incompatibleWith 누수 0
    for c in configs:
        for cpu in c["cpu_options"]:
            if _ask_incompat(cpu, c["mb"]):
                print(f"FAIL  예외 누수: {_ln(cpu)} <-> {_ln(c['mb'])}")
                ok = False
            # cpu_option 은 그 mb 와 socketCompatible 이어야 함
            if not _ask_rel(cpu, "socketCompatible", c["mb"]):
                print(f"FAIL  socketCompatible 불성립: {_ln(cpu)} -> {_ln(c['mb'])}")
                ok = False

    # 불변식 3: ram_option 전부 ramCompatible
    for c in configs:
        for ram in c["ram_options"]:
            if not _ask_rel(ram, "ramCompatible", c["mb"]):
                print(f"FAIL  ramCompatible 불성립: {_ln(ram)} -> {_ln(c['mb'])}")
                ok = False

    # 불변식 4: psu_option 전부 powerSufficient(psu, anchor)
    for psu in psus:
        if not _ask_rel(psu, "powerSufficient", anchor_iri):
            print(f"FAIL  powerSufficient 불성립: {_ln(psu)} -> anchor")
            ok = False

    if ok:
        print(f"PASS  Q3 건전성 (조합 {len(configs)}쌍 / PSU {len(psus)}개) - 매직넘버 0")
    return ok


# ===========================================================================
# 완전성(completeness): parts.yaml 단일출처를 오라클로 삼아 build_configuration 이
# "유효한 조합을 전부" 반환했는지 검사. soundness 의 역방향 가드.
#   - 기대 집합은 Fuseki 가 아니라 parts.yaml 에서 파생 (추론기 독립적 교차검증)
#   - 카운트 리터럴 대신 데이터 파생 -> 데이터 추가에도 자동 추종
# ===========================================================================
_PARTS_CANDIDATES = [
    os.environ.get("PARTS_YAML", ""),
    "/code/parts.yaml",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "parts.yaml"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts.yaml"),
]


def _find_parts() -> str | None:
    for p in _PARTS_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _derive_expected(parts: list, inc: list, anchor_local: str):
    """parts.yaml onto 스펙에서 build_configuration 기대 결과를 순수 파생."""
    onto = {p["iri"]: p["onto"] for p in parts}
    g = onto[anchor_local]
    glen = g["lengthMm"]
    need = g["recommendedWattage"] + g["powerMargin"]

    def of(t):
        return {p["iri"]: p["onto"] for p in parts if p["onto"]["type"] == t}
    cases, mbs = of("Case"), of("Motherboard")
    cpus, rams, psus = of("CPU"), of("RAM"), of("PSU")

    incset = set()
    for a, b in inc:
        incset.add((a, b)); incset.add((b, a))

    fit_cases = {c for c, o in cases.items() if glen <= o["maxGpuLengthMm"]}

    def mb_cpus(mb):
        sock = mbs[mb]["hasSocket"]
        return sorted(c for c, o in cpus.items()
                      if o["hasSocket"] == sock and (c, mb) not in incset)

    def mb_rams(mb):
        rt = mbs[mb]["supportsRAMType"]
        return sorted(r for r, o in rams.items() if o["hasRAMType"] == rt)

    expected = {}
    for mb, mo in mbs.items():
        ff = mo["hasFormFactor"]
        cpu_opts, ram_opts = mb_cpus(mb), mb_rams(mb)
        if not cpu_opts or not ram_opts:      # inner-join: 둘 다 있어야 쌍 성립
            continue
        for c in fit_cases:
            if ff in cases[c]["supportsFormFactor"]:
                expected[(mb, c)] = (cpu_opts, ram_opts)
    exp_psu = sorted(p for p, o in psus.items() if o["wattage"] >= need)
    return expected, exp_psu


def verify_q3_completeness(anchor_iri: str, parts_path: str) -> bool:
    """build_configuration(anchor) == parts.yaml 파생 기대치 인지 검사."""
    with open(parts_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    expected, exp_psu = _derive_expected(
        doc["parts"], doc.get("incompatible", []), _ln(anchor_iri)
    )

    result = build_configuration(anchor_iri)
    if "error" in result:
        print(f"FAIL  build_configuration error: {result['error']}")
        return False
    got = {
        (_ln(c["mb"]), _ln(c["case"])): (
            sorted(_ln(x) for x in c["cpu_options"]),
            sorted(_ln(x) for x in c["ram_options"]),
        )
        for c in result["configurations"]
    }
    got_psu = sorted(_ln(p) for p in result["psu_options"])

    ok = True
    if set(expected) != set(got):
        missing = sorted(set(expected) - set(got))
        extra   = sorted(set(got) - set(expected))
        if missing:
            print(f"FAIL  누락된 (mb,case) 쌍 (under-report): {missing}")
        if extra:
            print(f"FAIL  과잉 (mb,case) 쌍 (over-report): {extra}")
        ok = False
    for k in sorted(set(expected) & set(got)):
        if expected[k] != got[k]:
            print(f"FAIL  옵션 불일치 @ {k}: 기대={expected[k]} 실제={got[k]}")
            ok = False
    if exp_psu != got_psu:
        print(f"FAIL  PSU 불일치: 기대={exp_psu} 실제={got_psu}")
        ok = False

    if ok:
        print(f"PASS  Q3 완전성 (parts.yaml 파생 == build, "
              f"조합 {len(expected)}쌍 / PSU {len(exp_psu)}개) - 매직넘버 0")
    return ok


if __name__ == "__main__":
    r = resolve_entity("4080", "gpu")
    anchor = r.get("iri")
    if not anchor:
        print("FAIL  resolve_entity('4080','gpu') -> None (카탈로그 미스)")
        sys.exit(1)
    print(f"anchor = {_ln(anchor)}")

    ok = verify_q3_soundness(anchor)            # 건전성: 반환물 전부 유효한가

    parts_path = _find_parts()                  # 완전성: 유효한 게 전부 반환됐나
    if parts_path:
        ok &= verify_q3_completeness(anchor, parts_path)
    else:
        print("SKIP  완전성 검사 — parts.yaml 미발견 "
              f"(탐색: {[p for p in _PARTS_CANDIDATES if p]})")

    sys.exit(0 if ok else 1)
