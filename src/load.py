#!/usr/bin/env python3
"""작업5 적재기 — 단일 출처(parts.yaml) → 분기 적재.

  parts.yaml ──┬─► pc-data.ttl    (추론이 읽는 스펙/도출대상/예외)  [Fuseki]
               └─► catalog.sqlite (가격/재고/SKU/표시명/평점)       [RDB]
  다리 = IRI 하나. 한 출처에서 갈라쓰므로 IRI 드리프트 0.

불변식(위반 시 적재 실패):
  ① 모든 GPU 가 powerMargin 보유
  ② Q4 예외(incompatibleWith) 정확히 1쌍
  ③ IRI 유일
  ④ 온톨로지 IRI 집합 == RDB IRI 집합 (다리 정합)
"""
import sys, sqlite3, yaml
from pathlib import Path
from rdflib import Graph, Namespace, Literal, RDF
from rdflib.namespace import XSD

DATA = Path(__file__).resolve().parents[1] / "data"   # repo_root/data
SRC = str(DATA / "parts.yaml")
TTL = str(DATA / "pc-data.ttl")
DB  = str(DATA / "catalog.sqlite")

# onto 필드 분류
OBJ_SHARED = {  # 객체속성 → 통제어휘 개체 공유. (단일값/리스트)
    "hasSocket": "single", "supportsRAMType": "single", "hasRAMType": "single",
    "hasFormFactor": "single", "supportsFormFactor": "list",
}
NUM = {"wattage","recommendedWattage","powerMargin","lengthMm","maxGpuLengthMm"}
RDB_COLS = ["display_name","price_krw","stock","sku","rating"]


def fail(msg):
    print(f"[적재 실패] {msg}", file=sys.stderr); sys.exit(1)


def load_src():
    with open(SRC, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_invariants(doc):
    parts = doc["parts"]
    iris = [p["iri"] for p in parts]
    # ③ IRI 유일
    if len(iris) != len(set(iris)):
        dup = [x for x in iris if iris.count(x) > 1]
        fail(f"③ IRI 중복: {sorted(set(dup))}")
    # ① 모든 GPU powerMargin
    miss = [p["iri"] for p in parts
            if p["onto"]["type"] == "GPU" and "powerMargin" not in p["onto"]]
    if miss:
        fail(f"① powerMargin 누락 GPU: {miss}")
    # ② 예외 정확히 1쌍
    inc = doc.get("incompatible", [])
    if len(inc) != 1:
        fail(f"② incompatibleWith 쌍 = {len(inc)} (기대 1)")
    known = set(iris)
    for a, b in inc:
        if a not in known or b not in known:
            fail(f"② 예외가 미지 IRI 참조: {(a,b)}")
    print(f"불변식 ①②③ 통과  (부품 {len(parts)}, 예외 {len(inc)}쌍)")
    return parts, inc


def build_ttl(parts, inc, base):
    PC = Namespace(base)
    g = Graph(); g.bind("pc", PC)
    g.bind("xsd", XSD)
    for p in parts:
        s = PC[p["iri"]]; o = p["onto"]
        g.add((s, RDF.type, PC[o["type"]]))
        for k, v in o.items():
            if k == "type":
                continue
            if k in OBJ_SHARED:                       # 통제어휘 개체 공유
                vals = v if isinstance(v, list) else [v]
                for vv in vals:
                    g.add((s, PC[k], PC[str(vv)]))
            elif k in NUM:                            # 수치 리터럴
                g.add((s, PC[k], Literal(int(v), datatype=XSD.integer)))
            else:
                fail(f"미지 onto 필드 '{k}' @ {p['iri']}")
    # 예외 (symmetric → 양방향 적재)
    for a, b in inc:
        g.add((PC[a], PC.incompatibleWith, PC[b]))
        g.add((PC[b], PC.incompatibleWith, PC[a]))
    g.serialize(destination=TTL, format="turtle")
    onto_iris = {p["iri"] for p in parts}
    print(f"→ {TTL}  ({len(g)} 트리플)")
    return onto_iris


def build_db(parts):
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS catalog")
    cur.execute("""CREATE TABLE catalog(
        iri TEXT PRIMARY KEY, category TEXT NOT NULL,
        display_name TEXT, price_krw INTEGER, stock INTEGER,
        sku TEXT UNIQUE, rating REAL)""")
    for p in parts:
        r = p["rdb"]
        cur.execute("INSERT INTO catalog VALUES(?,?,?,?,?,?,?)",
                    (p["iri"], p["onto"]["type"],
                     r["display_name"], r["price_krw"], r["stock"], r["sku"], r["rating"]))
    con.commit()
    rdb_iris = {row[0] for row in cur.execute("SELECT iri FROM catalog")}
    con.close()
    print(f"→ {DB}  ({len(rdb_iris)} 행)")
    return rdb_iris


def main():
    doc = load_src()
    base = doc["meta"]["base"]
    parts, inc = check_invariants(doc)
    onto_iris = build_ttl(parts, inc, base)
    rdb_iris = build_db(parts)
    # ④ 다리 정합
    if onto_iris != rdb_iris:
        only_o = onto_iris - rdb_iris; only_r = rdb_iris - onto_iris
        fail(f"④ IRI 불일치  onto-only={only_o}  rdb-only={only_r}")
    print(f"불변식 ④ 통과  (온톨로지 IRI == RDB IRI, {len(onto_iris)}개)")
    print("적재 완료.")


if __name__ == "__main__":
    main()
