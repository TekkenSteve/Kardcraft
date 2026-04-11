"""Selector health metrics and threshold checks."""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class SelectorHealthSummary(TypedDict):
    total: int
    unavailable: int
    unavailable_rate: float
    no_match: int
    no_match_rate: float


def summarize_selector_health(results: List[Dict[str, Any]]) -> SelectorHealthSummary:
    total = max(0, len(results))
    unavailable = 0
    no_match = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        reason_codes = item.get("reason_codes") if isinstance(item.get("reason_codes"), list) else []
        normalized = {str(code or "").strip() for code in reason_codes if str(code or "").strip()}
        if "selector_unavailable" in normalized:
            unavailable += 1
        if "selector_no_match" in normalized:
            no_match += 1
    denominator = max(1, total)
    return {
        "total": total,
        "unavailable": unavailable,
        "unavailable_rate": unavailable / denominator,
        "no_match": no_match,
        "no_match_rate": no_match / denominator,
    }


def selector_unavailable_threshold_ok(
    summary: SelectorHealthSummary,
    *,
    max_unavailable_rate: float = 0.01,
) -> bool:
    return float(summary.get("unavailable_rate", 1.0) or 1.0) < float(max_unavailable_rate)

