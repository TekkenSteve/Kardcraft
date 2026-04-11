"""
Agent Skills System for Kardcraft

这是一个独立的 Agent Skills 实现，遵循 Agent Skills 标准规范。
设计用于在自定义 LangGraph 中使用，不依赖 DeepAgents 框架。

核心功能：
- 加载和解析 SKILL.md 文件（YAML frontmatter）
- 支持渐进式披露（progressive disclosure）
- 与 DeepAgents 使用方法相同，但完全独立实现

使用方法：
    from kardcraft.agent_skills import list_skills, SkillMetadata
    
    # 加载 skills
    skills = list_skills(project_skills_dir=".deepagents/skills")
    
    # 遍历 skills
    for skill in skills:
        print(skill['name'], skill['description'], skill['path'])

从 archive/DeepAgents-Skills 复制而来，保持原有实现。
"""

from .load import SkillMetadata, list_skills
from .middleware import SkillsMiddleware, NoSkillsMiddleware, SkillsState, SkillsStateUpdate
from .code import CodeMiddleware
from .shell import ShellMiddleware
from .router import (
    SkillSelectorUnavailableError,
    build_skill_guidance_text,
    select_skills_for_task,
    discover_skills,
    disclose_skills,
    replay_skill_selection,
)
from .selector_health import summarize_selector_health, selector_unavailable_threshold_ok

__all__ = [
    "SkillMetadata",
    "list_skills",
    "SkillsMiddleware",
    "NoSkillsMiddleware",
    "SkillsState",
    "SkillsStateUpdate",
    "CodeMiddleware",
    "ShellMiddleware",
    "build_skill_guidance_text",
    "select_skills_for_task",
    "discover_skills",
    "disclose_skills",
    "replay_skill_selection",
    "SkillSelectorUnavailableError",
    "summarize_selector_health",
    "selector_unavailable_threshold_ok",
]

__version__ = "1.0.0"
