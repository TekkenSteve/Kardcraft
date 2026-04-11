"""Skill router with progressive disclosure and isolated selector subagent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from deepagents import SubAgent, create_deep_agent
from pydantic import BaseModel, Field

from kardcraft.llm.discovery import get_model
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger

from .load import SkillMetadata, list_skills


class SkillSelectionResult(TypedDict, total=False):
    selected_skill_ids: List[str]
    selected_skill_names: List[str]
    reason_codes: List[str]
    confidence: float
    replay: Dict[str, Any]


class SkillSelectorUnavailableError(RuntimeError):
    """Raised when selector subagent is unavailable or returns invalid output."""


class _SelectorOutput(BaseModel):
    selected_skill_ids: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    confidence: float = 0.0


def _default_project_skills_dir() -> Path:
    return Path(__file__).resolve().parent.parent / ".deepagents" / "skills"


def discover_skills(
    *,
    project_skills_dir: Path | None = None,
    name_prefix: str | None = None,
) -> List[SkillMetadata]:
    skills = list_skills(project_skills_dir=project_skills_dir or _default_project_skills_dir())
    if name_prefix:
        return [s for s in skills if str(s.get("name") or "").startswith(name_prefix)]
    return skills


def _extract_selection_result(parsed: Dict[str, Any], available_names: set[str], max_selected: int) -> SkillSelectionResult:
    if not isinstance(parsed, dict):
        parsed = {}

    raw_names = parsed.get("selected_skill_ids") if isinstance(parsed.get("selected_skill_ids"), list) else []
    if not raw_names:
        raw_names = parsed.get("selected_skill_names") if isinstance(parsed.get("selected_skill_names"), list) else []
    selected: List[str] = []
    seen = set()
    for item in raw_names:
        name = str(item or "").strip()
        if not name or name in seen or name not in available_names:
            continue
        seen.add(name)
        selected.append(name)
        if len(selected) >= max_selected:
            break

    reason_codes_raw = parsed.get("reason_codes") if isinstance(parsed.get("reason_codes"), list) else []
    reason_codes = [str(x).strip() for x in reason_codes_raw if str(x).strip()][:4]
    if not reason_codes:
        reason_codes = ["selector_llm_no_reason_codes"]

    try:
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {"selected_skill_ids": selected, "selected_skill_names": selected, "reason_codes": reason_codes, "confidence": confidence}


def _build_selector_replay_record(
    *,
    task_context: str,
    available_skills: List[Dict[str, str]],
    max_selected: int,
    selection: SkillSelectionResult,
) -> Dict[str, Any]:
    return {
        "selector_version": "subagent_v1",
        "task_context": str(task_context or "")[:2000],
        "available_skills": [
            {"name": str(item.get("name") or "").strip(), "description": str(item.get("description") or "").strip()}
            for item in available_skills
            if str(item.get("name") or "").strip()
        ],
        "max_selected": int(max_selected),
        "selection": {
            "selected_skill_ids": list(selection.get("selected_skill_ids") or []),
            "reason_codes": list(selection.get("reason_codes") or []),
            "confidence": float(selection.get("confidence", 0.0) or 0.0),
        },
    }


def replay_skill_selection(replay: Dict[str, Any]) -> SkillSelectionResult:
    if not isinstance(replay, dict):
        return {
            "selected_skill_ids": [],
            "selected_skill_names": [],
            "reason_codes": ["selector_replay_invalid"],
            "confidence": 0.0,
        }
    available = replay.get("available_skills") if isinstance(replay.get("available_skills"), list) else []
    available_names = {
        str(item.get("name") or "").strip()
        for item in available
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    max_selected = int(replay.get("max_selected") or 6)
    selection = replay.get("selection") if isinstance(replay.get("selection"), dict) else {}
    normalized = _extract_selection_result(selection, available_names, max_selected=max_selected)
    normalized["replay"] = replay
    return normalized


async def _run_selector_subagent(
    *,
    task_context: str,
    available_skills: List[Dict[str, str]],
    max_selected: int,
) -> Dict[str, Any]:
    model_name, _ = get_model(intent="fast", temperature=0.0)
    selector_system_prompt = (
        "You are a selector subagent for multilingual workflow orchestration. "
        "Select the minimal relevant subset only from provided skill descriptions. "
        "Never select all skills unless strictly necessary. "
        "Return structured response only."
    )
    selector_subagent = SubAgent(
        name="skill-selector",
        description="Select minimal relevant skills from metadata descriptions only.",
        system_prompt=(
            "You must only use provided skill metadata (name and description). "
            "Do not assume hidden skill contents. "
            "Output structured fields only."
        ),
        tools=[],
    )
    payload = {
        "task_context": str(task_context or "")[:2000],
        "available_skills": available_skills,
        "max_selected": max_selected,
        "selection_policy": "minimal_relevant_set",
        "constraints": [
            "metadata_only",
            "description_only",
            "no_skill_body_access",
        ],
    }
    agent = create_deep_agent(
        model=model_name,
        tools=[],
        system_prompt=selector_system_prompt,
        subagents=[selector_subagent],
        response_format=_SelectorOutput,
        name="skill_selector_router",
    )
    result = await agent.ainvoke({"messages": [("user", json.dumps(payload, ensure_ascii=False))]})
    structured = None
    if isinstance(result, dict):
        structured = (
            result.get("structured_response")
            or result.get("output")
            or result.get("response")
        )
        if structured is None and result.get("messages"):
            messages = result.get("messages") or []
            last = messages[-1]
            content = str(getattr(last, "content", last) or "")
            structured = safe_parse_llm_json(content, default={})
    if isinstance(structured, BaseModel):
        return structured.model_dump()
    if isinstance(structured, dict):
        return structured
    raise SkillSelectorUnavailableError("selector_invalid_output")


async def select_skills_for_task(
    *,
    task_context: str,
    skills: List[SkillMetadata],
    max_selected: int = 6,
) -> SkillSelectionResult:
    if not skills:
        return {"selected_skill_ids": [], "selected_skill_names": [], "reason_codes": ["no_skills_available"], "confidence": 1.0}

    available = []
    for item in skills:
        name = str(item.get("name") or "").strip()
        desc = str(item.get("description") or "").strip()
        if not name:
            continue
        available.append({"name": name, "description": desc})
    if not available:
        return {"selected_skill_ids": [], "selected_skill_names": [], "reason_codes": ["no_skill_metadata"], "confidence": 1.0}

    try:
        parsed = await _run_selector_subagent(
            task_context=task_context,
            available_skills=available,
            max_selected=max_selected,
        )
        result = _extract_selection_result(
            parsed=parsed,
            available_names={x["name"] for x in available},
            max_selected=max_selected,
        )
        if not result["selected_skill_names"]:
            result["reason_codes"] = ["selector_no_match"]
        result["replay"] = _build_selector_replay_record(
            task_context=task_context,
            available_skills=available,
            max_selected=max_selected,
            selection=result,
        )
        return result
    except Exception as exc:
        logger.error("skill selector subagent unavailable", error=str(exc))
        unavailable: SkillSelectionResult = {
            "selected_skill_ids": [],
            "selected_skill_names": [],
            "reason_codes": ["selector_unavailable"],
            "confidence": 0.0,
        }
        unavailable["replay"] = _build_selector_replay_record(
            task_context=task_context,
            available_skills=available,
            max_selected=max_selected,
            selection=unavailable,
        )
        return unavailable


def _strip_frontmatter(content: str) -> str:
    match = re.match(r"^---\s*\n.*?\n---\s*\n", content, flags=re.DOTALL)
    if not match:
        return content
    return content[match.end() :]


def disclose_skills(
    *,
    selected_names: List[str],
    skills: List[SkillMetadata],
) -> List[Dict[str, str]]:
    by_name = {str(item.get("name") or "").strip(): item for item in skills}
    out: List[Dict[str, str]] = []
    for name in selected_names:
        metadata = by_name.get(str(name or "").strip())
        if not metadata:
            continue
        path = Path(str(metadata.get("path") or "")).expanduser()
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        body = _strip_frontmatter(raw).strip()
        snippet = re.sub(r"\s+", " ", body)[:220].strip()
        out.append(
            {
                "name": str(metadata.get("name") or "").strip(),
                "description": str(metadata.get("description") or "").strip(),
                "path": str(path),
                "snippet": snippet,
            }
        )
    return out


async def build_skill_guidance_text(
    *,
    task_context: str,
    header: str,
    name_prefix: str = "principle-",
    max_selected: int = 6,
    project_skills_dir: Path | None = None,
) -> tuple[str, SkillSelectionResult]:
    skills = discover_skills(project_skills_dir=project_skills_dir, name_prefix=name_prefix)
    selection = await select_skills_for_task(
        task_context=task_context,
        skills=skills,
        max_selected=max_selected,
    )
    if "selector_unavailable" in selection.get("reason_codes", []):
        raise SkillSelectorUnavailableError("selector_unavailable")
    disclosed = disclose_skills(selected_names=selection["selected_skill_names"], skills=skills)
    if not disclosed:
        return "", selection
    lines = [header]
    for item in disclosed:
        name = item.get("name", "")
        desc = item.get("description", "")
        if name and desc:
            lines.append(f"- {name}: {desc}")
        elif name:
            lines.append(f"- {name}")
    return "\n".join(lines), selection
