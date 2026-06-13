#!/usr/bin/env python3
"""parts.yaml 단일출처에서 Fuseki 검증 기대치를 순수 파생하는 오라클.

손-리터럴 기대값(brittleness)을 폐기한다: Q1/Q2/Q3/Q5 의 기대 집합을
추론기와 독립적으로 parts.yaml 의 onto 스펙에서 재계산한다. 규칙의 의미는
pc-data.ttl 에 적재되는 추론 규칙과 동일하게 재현하되 구현은 독립이므로
(데이터→기대) 와 (데이터→TTL→Fuseki) 두 경로가 교차검증된다. 데이터가
늘어도 기대치가 자동 추종 → 매직넘버 0.

규칙(의미는 pc-data.ttl 적재본과 동치):
  socketCompatible(cpu, mb) := cpu.hasSocket == mb.hasSocket     # 순수 소켓 일치
                                                                 # (incompatibleWith 예외는 앱계층)
  powerSufficient(psu, gpu) := psu.wattage >= gpu.recWatt + gpu.powerMargin
  gpuFitsCase(gpu, case)    := gpu.lengthMm <= case.maxGpuLengthMm
  boardFitsCase(mb, case)   := mb.hasFormFactor ∈ case.supportsFormFactor
"""
import os

import yaml

# verify_q3._PARTS_CANDIDATES 와 동일한 탐색 순서(컨테이너 /code, 로컬 data/).
_PARTS_CANDIDATES = [
    os.environ.get("PARTS_YAML", ""),
    "/code/parts.yaml",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "parts.yaml"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts.yaml"),
]


class OracleError(RuntimeError):
    """parts.yaml 미발견 등 기대치 산출 불가 — 검증은 SKIP 이 아니라 하드 실패해야 한다."""


def find_parts() -> str:
    for p in _PARTS_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise OracleError(
        "parts.yaml 미발견 — 기대치를 파생할 수 없어 검증 불가 "
        f"(탐색: {[p for p in _PARTS_CANDIDATES if p]})"
    )


class Oracle:
    """parts.yaml onto 스펙을 색인하고 규칙별 기대 집합(=localname)을 산출."""

    def __init__(self, parts_path: str | None = None):
        self.path = parts_path or find_parts()
        with open(self.path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        self.parts = doc["parts"]
        self.onto = {p["iri"]: p["onto"] for p in self.parts}
        self.incompat: set[tuple[str, str]] = set()
        for a, b in doc.get("incompatible", []):
            self.incompat.add((a, b))
            self.incompat.add((b, a))

    def _of(self, t: str) -> dict:
        return {iri: o for iri, o in self.onto.items() if o["type"] == t}

    # --- 규칙별 파생 (집합 = localname) ------------------------------------
    def socket_compatible(self, cpu: str) -> set[str]:
        """socketCompatible(cpu, ?mb): 순수 소켓 일치(예외 미적용 — Fuseki 의미와 동일)."""
        sock = self.onto[cpu]["hasSocket"]
        return {mb for mb, o in self._of("Motherboard").items() if o["hasSocket"] == sock}

    def socket_compatible_pair(self, cpu: str, mb: str) -> bool:
        return self.onto[cpu]["hasSocket"] == self.onto[mb]["hasSocket"]

    def power_sufficient(self, gpu: str) -> set[str]:
        """powerSufficient(?psu, gpu): wattage >= recWatt + powerMargin."""
        o = self.onto[gpu]
        need = o["recommendedWattage"] + o["powerMargin"]
        return {psu for psu, po in self._of("PSU").items() if po["wattage"] >= need}

    def power_sufficient_pair(self, psu: str, gpu: str) -> bool:
        o = self.onto[gpu]
        return self.onto[psu]["wattage"] >= o["recommendedWattage"] + o["powerMargin"]

    def gpu_fits_case(self, gpu: str) -> set[str]:
        """gpuFitsCase(gpu, ?case): lengthMm <= maxGpuLengthMm."""
        glen = self.onto[gpu]["lengthMm"]
        return {c for c, o in self._of("Case").items() if glen <= o["maxGpuLengthMm"]}

    def board_fits_case_pairs(self, form_factor: str | None = None) -> set[tuple[str, str]]:
        """boardFitsCase(?mb, ?case) 쌍. form_factor 지정 시 그 폼팩터 보드만."""
        cases = self._of("Case")
        pairs: set[tuple[str, str]] = set()
        for mb, mo in self._of("Motherboard").items():
            ff = mo["hasFormFactor"]
            if form_factor and ff != form_factor:
                continue
            for c, co in cases.items():
                if ff in co["supportsFormFactor"]:
                    pairs.add((mb, c))
        return pairs
