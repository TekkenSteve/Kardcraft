"""Quality report metric helpers."""

from __future__ import annotations

from typing import Any, Dict


def reason_code_coverage_rate(report: Dict[str, Any]) -> float:
    failed_cards = report.get("failed_cards") if isinstance(report.get("failed_cards"), list) else []
    if not failed_cards:
        return 1.0
    covered = 0
    for item in failed_cards:
        if not isinstance(item, dict):
            continue
        codes = item.get("reason_codes")
        if not isinstance(codes, list):
            continue
        if any(str(code or "").strip() for code in codes):
            covered += 1
    return covered / max(1, len(failed_cards))


def reason_code_coverage_ok(report: Dict[str, Any], *, threshold: float = 1.0) -> bool:
    return reason_code_coverage_rate(report) >= float(threshold)

