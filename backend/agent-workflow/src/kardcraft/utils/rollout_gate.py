"""Rollout gate for evidence/skill-router architecture."""

from __future__ import annotations

import hashlib
import os
from typing import Dict

ROLLOUT_MODE_ENV = "KARD_EVIDENCE_SKILL_ROUTER_ROLLOUT_MODE"
ROLLOUT_PERCENT_ENV = "KARD_EVIDENCE_SKILL_ROUTER_ROLLOUT_PERCENT"
ROLLOUT_ALLOWLIST_ENV = "KARD_EVIDENCE_SKILL_ROUTER_ROLLOUT_USERS"


def _stable_bucket(user_id: str) -> int:
    digest = hashlib.sha256(str(user_id or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def rollout_enabled_for_user(user_id: str | None) -> Dict[str, object]:
    mode = str(os.getenv(ROLLOUT_MODE_ENV, "on") or "on").strip().lower()
    percent_raw = str(os.getenv(ROLLOUT_PERCENT_ENV, "100") or "100").strip()
    allowlist_raw = str(os.getenv(ROLLOUT_ALLOWLIST_ENV, "") or "").strip()
    allowlist = {x.strip() for x in allowlist_raw.split(",") if x.strip()}

    try:
        percent = max(0, min(100, int(percent_raw)))
    except Exception:
        percent = 100

    normalized_user = str(user_id or "").strip()
    in_allowlist = bool(normalized_user and normalized_user in allowlist)
    if mode == "off":
        enabled = False
    elif mode == "on":
        enabled = True
    elif mode == "canary":
        bucket = _stable_bucket(normalized_user)
        enabled = in_allowlist or bucket < percent
    else:
        enabled = True

    return {
        "mode": mode,
        "percent": percent,
        "enabled": enabled,
        "in_allowlist": in_allowlist,
    }

