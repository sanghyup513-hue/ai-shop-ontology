#!/usr/bin/env python3
"""작업5 재검증 — 확대 데이터(load.py 산출물)로 Q1~Q5 한 바퀴.

※ 이 스크립트는 핸드오프 v1.5 스펙(작업1 5규칙 / 작업3 경계)을 재구성한 드라이런이다.
   Claude Code 세션의 실제 validate.py/tools.py/rdb_boundary.py 가 있으면 그쪽에
   pc-data.ttl + catalog.sqlite 를 그대로 물리면 된다(인터페이스 동일).

규칙(작업1, 4슬롯: ①타입가드 ②조인 ③예외가드(noValue) ④사유술어):
  패턴1(공유개체 조인): socketCompatible(CPU,MB) ramCompatible(RAM,MB) boardFitsCase(MB,Case)
  패턴2(수치 빌트인):    powerSufficient(PSU,GPU; sum+ge)  gpuFitsCase(GPU,Case; le)
"""
import sqlite3, time
from pathlib import Path
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

PC = Namespace("http://example.org/pc#")
DATA = Path(__file__).resolve().parents[1] / "data"
TTL, DB = str(DATA / "pc-data.ttl"), str(DATA / "catalog.sqlite")


def materialize(g):
    """5규칙 forward-chaining. 도출 사실을 그래프에 펼쳐 적재(런타임은 조회만)."""
    def inc(a, b):                       # ③ 예외가드 (symmetric)
        return (a, PC.incompatibleWith, b) in g or (b, PC.incompatibleWith, a) in g
    def insts(t): return set(g.subjects(RDF.type, PC[t]))
    def one(s, p):
        v = list(g.objects(s, PC[p])); return v[0] if v else None
    def num(s, p):
        v = one(s, p); return int(v) if v is not None else None

    added = 0
    # 패턴1 — socketCompatible(CPU,MB)
    for c in insts("CPU"):
        for m in insts("Motherboard"):
            if one(c, "hasSocket") and one(c, "hasSocket") == one(m, "hasSocket") and not inc(c, m):
                g.add((c, PC.socketCompatible, m)); added += 1
    # 패턴1 — ramCompatible(RAM,MB)
    for r in insts("RAM"):
        for m in insts("Motherboard"):
            if one(r, "hasRAMType") and one(r, "hasRAMType") == one(m, "supportsRAMType") and not inc(r, m):
                g.add((r, PC.ramCompatible, m)); added += 1
    # 패턴1 — boardFitsCase(MB,Case)  (Case.supportsFormFactor 다중)
    for m in insts("Motherboard"):
        ff = one(m, "hasFormFactor")
        for ca in insts("Case"):
            if ff and ff in set(g.objects(ca, PC.supportsFormFactor)) and not inc(m, ca):
                g.add((m, PC.boardFitsCase, ca)); added += 1
    # 패턴2 — powerSufficient(PSU,GPU): wattage >= recommendedWattage + powerMargin
    for ps in insts("PSU"):
        w = num(ps, "wattage")
        for gp in insts("GPU"):
            need = num(gp, "recommendedWattage") + num(gp, "powerMargin")
            if w is not None and w >= need and not inc(ps, gp):
                g.add((ps, PC.powerSufficient, gp)); added += 1
    # 패턴2 — gpuFitsCase(GPU,Case): lengthMm <= maxGpuLengthMm
    for gp in insts("GPU"):
        L = num(gp, "lengthMm")
        for ca in insts("Case"):
            if L is not None and L <= num(ca, "maxGpuLengthMm") and not inc(gp, ca):
                g.add((gp, PC.gpuFitsCase, ca)); added += 1
    return added


def ln(uri): return str(uri).split("#")[-1]


def main():
    g = Graph(); g.parse(TTL, format="turtle")
    base = len(g)
    t0 = time.perf_counter()
    added = materialize(g)
    dt = (time.perf_counter() - t0) * 1000
    print(f"머티리얼라이즈: 기초 {base} + 도출 {added} = {len(g)} 트리플  ({dt:.1f} ms)\n")

    def q(sparql, **b):
        return [tuple(ln(x) for x in row) for row in g.query(sparql, initBindings=b)]

    # Q1 — 소켓 매칭: 7700X 에 맞는 MB
    r = q("SELECT ?m WHERE { ?cpu pc:socketCompatible ?m }", cpu=PC.cpu_ryzen7_7700x)
    print("Q1 소켓매칭  7700X →", sorted(x[0] for x in r))

    # Q2 — 전력 임계값(≥) 경계: 4080(필요510)에 맞는 PSU
    r = q("SELECT ?p WHERE { ?p pc:powerSufficient ?g }", g=PC.gpu_rtx4080)
    print("Q2 전력경계  4080(필요510) → PSU", sorted(x[0] for x in r),
          " [510통과/500탈락 기대]")

    # Q3 — 다중제약 견적(GPU 앵커 4080) → 플랫폼 비고정(AM5/LGA1700 둘 다)
    sets = q("""SELECT ?cpu ?mb ?ram ?psu ?case WHERE {
        ?psu pc:powerSufficient ?g .
        ?g  pc:gpuFitsCase ?case .
        ?mb pc:boardFitsCase ?case .
        ?cpu pc:socketCompatible ?mb .
        ?ram pc:ramCompatible ?mb .
    }""", g=PC.gpu_rtx4080)
    plats = {("AM5" if "ryzen" in c else "LGA1700") for c, *_ in sets}
    print(f"Q3 다중제약  4080 견적 {len(sets)}세트, 플랫폼={sorted(plats)} [복수 기대]")

    # Q4 — 예외 우선순위: i5_14600k ↔ b760_ddr4 (소켓 LGA1700 일치인데 호환 탈락?)
    shared = (one := list(g.objects(PC.cpu_i5_14600k, PC.hasSocket))) and \
             one == list(g.objects(PC.mb_b760_ddr4, PC.hasSocket))
    derived = (PC.cpu_i5_14600k, PC.socketCompatible, PC.mb_b760_ddr4) in g
    print(f"Q4 예외      소켓공유={bool(shared)} / socketCompatible도출={derived} "
          f"[공유True·도출False 기대]")

    # Q5 — 설명가능성: 왜 호환? 사유술어 + 값(basis)
    w = int(list(g.objects(PC.psu_510w, PC.wattage))[0])
    need = sum(int(list(g.objects(PC.gpu_rtx4080, PC[p]))[0])
               for p in ("recommendedWattage", "powerMargin"))
    ok = (PC.psu_510w, PC.powerSufficient, PC.gpu_rtx4080) in g
    print(f"Q5 설명      psu_510w powerSufficient gpu_rtx4080 = {ok} "
          f"(basis: wattage {w} ≥ rec+margin {need})")

    # ---- 작업3 경계 실익: RDB 후필터 + 재머티리얼라이즈 0회 ----
    print("\n[RDB 경계]")
    con = sqlite3.connect(DB); cur = con.cursor()
    # 온톨로지 우선(7700X 호환 MB) → IRI로 RDB 후필터(가격 80만원대)
    mb_iris = sorted(x[0] for x in
                     q("SELECT ?m WHERE { ?c pc:socketCompatible ?m }", c=PC.cpu_ryzen7_7700x))
    ph = ",".join("?" * len(mb_iris))
    rows = cur.execute(
        f"SELECT display_name, price_krw FROM catalog "
        f"WHERE iri IN ({ph}) AND price_krw BETWEEN 800000 AND 899999", mb_iris).fetchall()
    print("  7700X 호환 & 80만원대 보드 →", rows)

    # 가격만 변경 → 재추론 불필요(경계의 실익): 머티 재실행 0회로 견적 불변
    cur.execute("UPDATE catalog SET price_krw=999000 WHERE iri='mb_x670e_atx'"); con.commit()
    remat_after_price_change = 0
    still = (PC.cpu_ryzen7_7700x, PC.socketCompatible, PC.mb_x670e_atx) in g
    print(f"  가격 변경 후 재머티리얼라이즈 {remat_after_price_change}회, "
          f"호환사실 유지={still} [0회·유지 기대]")
    con.close()


if __name__ == "__main__":
    main()
