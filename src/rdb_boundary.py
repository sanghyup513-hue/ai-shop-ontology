"""RDB 경계 — 관계형 데이터(표시명·가격) 접근.

v2.4 역할분리: 더 이상 catalog.sqlite 를 직접 열지 않는다. 별도 컨테이너로 분리된
rdb 서비스(rdb_service.py)를 HTTP 로 호출한다. 함수 시그니처는 보존하므로
tools.py / agent_loop.py 는 변경 없음.

설계: 온톨로지(Fuseki)에는 IRI/구조만, 사람용 메타(표시명·가격·SKU)는 rdb 서비스.
다리 = IRI 하나.
"""
import os
import json
import urllib.request

RDB_URL = os.environ.get("RDB_URL", "http://rdb-svc:8081").rstrip("/")
_TIMEOUT = float(os.environ.get("RDB_TIMEOUT", "10"))


def _post(path: str, iris):
    iris = list(iris)
    if not iris:
        return {}
    req = urllib.request.Request(
        f"{RDB_URL}{path}",
        data=json.dumps({"iris": iris}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def resolve_display_names(iris):
    """IRI 목록 → {iri: display_name}. rdb 서비스 미스/장애 시 IRI 원본을 값으로 폴백."""
    iris = list(iris)
    if not iris:
        return {}
    try:
        return _post("/resolve-names", iris)
    except Exception:
        # rdb 서비스 장애 시에도 추론·발화는 계속 — IRI 를 표시명 대신 노출(degraded).
        return {iri: iri for iri in iris}


def product_info(iris):
    """IRI 목록 → {iri: {category,name,price_krw,stock,sku,rating}}. 장애 시 {}."""
    try:
        return _post("/info", iris)
    except Exception:
        return {}


def search_by_name(text, category):
    """표시명 부분일치 검색 → [localname]. resolve_entity 의 RDB arm. 장애 시 []."""
    if not text:
        return []
    try:
        req = urllib.request.Request(
            f"{RDB_URL}/search",
            data=json.dumps({"text": text, "category": category}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")).get("matches", [])
    except Exception:
        return []
