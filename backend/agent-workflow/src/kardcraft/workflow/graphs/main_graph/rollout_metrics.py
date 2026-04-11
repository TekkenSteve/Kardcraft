"""Rollout observability helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def failure_reason_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or item.get("error") or "").strip() or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def quality_threshold_not_met_ratio(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    counts = failure_reason_distribution(results)
    failed_total = sum(v for k, v in counts.items() if k != "quality_pass")
    if failed_total <= 0:
        return 0.0
    return counts.get("quality_threshold_not_met", 0) / failed_total

