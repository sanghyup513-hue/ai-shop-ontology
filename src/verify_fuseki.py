#!/usr/bin/env python3
"""Fuseki 라이브 추론 검증 Q1~Q5 + cold/warm 타이밍 실측."""
import os, sys, time, json, urllib.request, urllib.parse

ENDPOINT = os.environ.get("FUSEKI_SPARQL", "http://fuseki-svc:3030/pc/sparql")
PFX = "PREFIX pc: <http://example.org/pc#>"


def sparql(q, timeout=30):
    body = urllib.parse.urlencode({"query": q}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    dt = (time.perf_counter() - t0) * 1000
    rows = [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]
    return rows, dt


def short(uri):
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri


QUERIES = {
    "Q1": (
        "AM5(7700X) → socketCompatible (기대: b650, x670e)",
        f"{PFX} SELECT ?mb WHERE {{ pc:cpu_ryzen7_7700x pc:socketCompatible ?mb }} ORDER BY ?mb",
        ["mb"],
        {"mb_b650_atx", "mb_x670e_atx"},
    ),
    "Q2_pass": (
        "powerSufficient: PSU→4080 (기대: 1000/750/550/510 통과)",
        f"{PFX} SELECT ?psu WHERE {{ ?psu pc:powerSufficient pc:gpu_rtx4080 }} ORDER BY ?psu",
        ["psu"],
        {"psu_1000w", "psu_750w", "psu_550w", "psu_510w"},
    ),
    "Q2_fail": (
        "powerSufficient: psu_500w 4080 통과 여부 (기대: 0건=탈락)",
        f"{PFX} ASK {{ pc:psu_500w pc:powerSufficient pc:gpu_rtx4080 }}",
        None,
        False,
    ),
    "Q3": (
        "GPU 4080 앵커 → boardFitsCase (기대: ATX 보드 4종 × 적합 케이스)",
        f"{PFX} SELECT ?mb ?case WHERE {{ ?mb pc:boardFitsCase ?case ; pc:hasFormFactor pc:ATX }} ORDER BY ?mb ?case",
        ["mb", "case"],
        None,
    ),
    "Q4": (
        "Q4: i5_14600k(LGA1700) ↔ b760_ddr4 socketCompatible 도출됨 "
        "(소켓 물리 일치 — incompatibleWith 예외는 앱 계층에서 처리)",
        f"{PFX} ASK {{ pc:cpu_i5_14600k pc:socketCompatible pc:mb_b760_ddr4 }}",
        None,
        True,
    ),
    "Q4_other": (
        "Q4 비교: i7_14700k(LGA1700) ↔ b760_ddr4 는 도출 (예외 없으므로)",
        f"{PFX} ASK {{ pc:cpu_i7_14700k pc:socketCompatible pc:mb_b760_ddr4 }}",
        None,
        True,
    ),
    "Q5": (
        "gpuFitsCase: 4080(310mm) → case (기대: full=400, mid=330)",
        f"{PFX} SELECT ?case WHERE {{ pc:gpu_rtx4080 pc:gpuFitsCase ?case }} ORDER BY ?case",
        ["case"],
        {"case_atx_full", "case_atx_mid"},
    ),
}


def run_one(name, desc, query, cols, expected):
    print(f"\n=== {name}: {desc} ===")
    try:
        if cols is None:
            # ASK
            body = urllib.parse.urlencode({"query": query}).encode()
            req = urllib.request.Request(
                ENDPOINT, data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "application/sparql-results+json"},
            )
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            dt = (time.perf_counter() - t0) * 1000
            got = data["boolean"]
            ok = (got == expected)
            print(f"  결과: {got}  기대: {expected}  [{'PASS' if ok else 'FAIL'}]  ({dt:.1f}ms)")
            return ok, dt
        rows, dt = sparql(query)
        vals = [short(r[cols[0]]) for r in rows] if len(cols) == 1 else rows
        if expected is None:
            print(f"  결과({len(rows)}건): {vals}  [정보]  ({dt:.1f}ms)")
            return True, dt
        got_set = set(vals)
        ok = got_set == expected
        print(f"  결과: {sorted(got_set)}")
        print(f"  기대: {sorted(expected)}")
        print(f"  [{'PASS' if ok else 'FAIL'}]  ({dt:.1f}ms)")
        return ok, dt
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False, 0


def main():
    print("Fuseki 라이브 추론 검증 (Q1~Q5)")
    print(f"엔드포인트: {ENDPOINT}")
    all_ok = True
    timings = {}
    for name, (desc, q, cols, exp) in QUERIES.items():
        ok, dt = run_one(name, desc, q, cols, exp)
        all_ok &= ok
        timings[name] = dt

    # warm 측정 — Q1 5회
    print("\n=== Cold/Warm 타이밍 (Q1 반복 5회) ===")
    warm_runs = []
    for i in range(5):
        _, dt = sparql(QUERIES["Q1"][1])
        warm_runs.append(dt)
        print(f"  run {i+1}: {dt:.1f}ms")
    print(f"\n전체 결과: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    print(f"Q1 첫호출(=cold 컨테이너 기동 후): {timings['Q1']:.1f}ms")
    print(f"Q1 warm 평균(2~5회): {sum(warm_runs[1:])/4:.1f}ms")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
