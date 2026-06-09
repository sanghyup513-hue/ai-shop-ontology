"""RDB 경계 — 카탈로그 SQLite 접근.

설계: 온톨로지(Fuseki)에는 IRI/구조만, 사람용 메타(표시명·가격·SKU)는 SQLite.
catalog.iri 컬럼은 localname 저장이므로 PC 접두어 제거 후 매칭.
"""
import os
import sqlite3

PC = "http://example.org/pc#"
DB_PATH = os.environ.get("CATALOG_DB", "data/catalog.sqlite")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _to_localname(iri: str) -> str:
    return iri[len(PC):] if iri.startswith(PC) else iri


def resolve_display_names(iris):
    """IRI 목록 → {iri: display_name}. 카탈로그 미스 시 IRI 원본을 그대로 값으로."""
    if not iris:
        return {}
    keys = [_to_localname(i) for i in iris]
    placeholders = ",".join("?" * len(keys))
    rows = _conn().execute(
        f"SELECT iri, display_name FROM catalog WHERE iri IN ({placeholders})",
        keys,
    ).fetchall()
    by_local = {r["iri"]: r["display_name"] for r in rows}
    return {orig: by_local.get(_to_localname(orig), orig) for orig in iris}
