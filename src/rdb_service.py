# src/rdb_service.py — RDB 경계 서비스 (stdlib only, 무의존)
#
# 역할 분리: 관계형 데이터(표시명·가격·재고·평점·SKU)의 단독 권한자.
# catalog.sqlite 를 소유하고 HTTP 로 노출 — web/agent 컨테이너는 이 서비스를
# 통해서만 표시명을 얻는다(파일 직접 접근 X). 온톨로지/추론과 완전 분리.
#
# 엔드포인트:
#   GET  /health         {ok, rows}
#   GET  /catalog        관계형 행 전체 [{iri, category, name, price, stock, rating}]
#   POST /resolve-names  {"iris":[...]} → {iri: display_name}  (미스 시 IRI 원본)
#
# 환경변수: CATALOG_DB(/code/catalog.sqlite) / PORT(8081) / PC_NS

import os
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = os.environ.get("CATALOG_DB", "/code/catalog.sqlite")
PORT    = int(os.environ.get("PORT", "8081"))
PC      = os.environ.get("PC_NS", "http://example.org/pc#")


def _to_local(iri: str) -> str:
    return iri[len(PC):] if iri.startswith(PC) else iri


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def resolve_names(iris):
    """IRI 목록 → {iri: display_name}. catalog.iri 는 localname 저장이므로 접두어 제거 후 매칭."""
    iris = list(iris)
    if not iris:
        return {}
    keys = [_to_local(i) for i in iris]
    ph = ",".join("?" * len(keys))
    rows = _conn().execute(
        f"SELECT iri, display_name FROM catalog WHERE iri IN ({ph})", keys
    ).fetchall()
    by_local = {r["iri"]: r["display_name"] for r in rows}
    return {orig: by_local.get(_to_local(orig), orig) for orig in iris}


def product_info(iris):
    """IRI 목록 → {iri: {category,name,price_krw,stock,sku,rating}}. 미스는 제외."""
    iris = list(iris)
    if not iris:
        return {}
    keys = [_to_local(i) for i in iris]
    ph = ",".join("?" * len(keys))
    rows = _conn().execute(
        f"SELECT iri, category, display_name, price_krw, stock, sku, rating "
        f"FROM catalog WHERE iri IN ({ph})", keys
    ).fetchall()
    by_local = {r["iri"]: r for r in rows}
    out = {}
    for orig in iris:
        r = by_local.get(_to_local(orig))
        if r:
            out[orig] = {
                "category": r["category"], "name": r["display_name"],
                "price_krw": r["price_krw"], "stock": r["stock"],
                "sku": r["sku"], "rating": r["rating"],
            }
    return out


def search_by_name(text, category):
    """표시명 부분일치(대소문자 무시) + 카테고리 클래스 필터 → [localname]. resolve_entity arm2."""
    text = (text or "").strip()
    if not text:
        return []
    rows = _conn().execute(
        "SELECT iri FROM catalog WHERE category = ? AND LOWER(display_name) LIKE ? ORDER BY iri",
        (category, f"%{text.lower()}%"),
    ).fetchall()
    return [r["iri"] for r in rows]


def catalog_rows():
    rows = _conn().execute(
        "SELECT iri, category, display_name, price_krw, stock, rating "
        "FROM catalog ORDER BY category, iri"
    ).fetchall()
    return [
        {
            "iri":    r["iri"],
            "category": r["category"],
            "name":   r["display_name"],
            "price":  r["price_krw"],
            "stock":  r["stock"],
            "rating": r["rating"],
        }
        for r in rows
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "RdbService/1.0"

    def _send(self, code: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            try:
                n = _conn().execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
                self._send(200, {"ok": True, "rows": n})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(e)})
        elif path == "/catalog":
            self._send(200, catalog_rows())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/resolve-names", "/info", "/search"):
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if path == "/search":
                self._send(200, {"matches": search_by_name(payload.get("text", ""),
                                                            payload.get("category", ""))})
            else:
                iris = payload.get("iris", [])
                self._send(200, resolve_names(iris) if path == "/resolve-names" else product_info(iris))
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    n = _conn().execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    print(f"[rdb] catalog service listening on :{PORT}  (db={DB_PATH}, {n} rows)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
