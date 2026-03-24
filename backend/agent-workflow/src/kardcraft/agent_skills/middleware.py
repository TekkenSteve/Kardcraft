"""Middleware for loading and exposing agent skills to the system prompt.

This middleware implements Anthropic's "Agent Skills" pattern with progressive disclosure:
1. Parse YAML frontmatter from SKILL.md files at session start
2. Inject skills metadata (name + description) into system prompt
3. Agent reads full SKILL.md content when relevant to a task

Copied from archive/DeepAgents-Skills/skills/middleware.py
"""

from collections.abc import Callable
from pathlib import Path
from typing import NotRequired, TypedDict, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langgraph.runtime import Runtime

from .load import SkillMetadata, list_skills


class SkillsState(AgentState):
    """State for the skills middleware."""

    skills_metadata: NotRequired[list[SkillMetadata]]
    """List of loaded skill metadata (name, description, path)."""


class SkillsStateUpdate(TypedDict):
    """State update for the skills middleware."""

    skills_metadata: list[SkillMetadata]
    """List of loaded skill metadata (name, description, path)."""


# Skills System Documentation
SKILLS_SYSTEM_PROMPT = """

## Skills System

You have access to a skills library that provides specialized capabilities and domain knowledge.

{skills_locations}

**Available Skills:**

{skills_list}

**How to Use Skills (Progressive Disclosure):**

Skills follow a **progressive disclosure** pattern - you know they exist (name + description above), but you only read the full instructions when needed:

1. **Recognize when a skill applies**: Check if the user's task matches any skill's description
2. **Read the skill's full instructions**: The skill list above shows the exact path to use with read_file
3. **Follow the skill's instructions**: SKILL.md contains step-by-step workflows, best practices, and examples
4. **Access supporting files**: Skills may include Python scripts, configs, or reference docs - use absolute paths

**When to Use Skills:**
- When the user's request matches a skill's domain (e.g., "research X" → web-research skill)
- When you need specialized knowledge or structured workflows
- When a skill provides proven patterns for complex tasks

**Skills are Self-Documenting:**
- Each SKILL.md tells you exactly what the skill does and how to use it
- The skill list above shows the full path for each skill's SKILL.md file

**Executing Skill Scripts:**
Skills may contain Python scripts or other executable files. Always use absolute paths from the skill list.

**Example Workflow:**

User: "Can you research the latest developments in quantum computing?"

1. Check available skills above → See "web-research" skill with its full path
2. Read the skill using the path shown in the list
3. Follow the skill's research workflow (search → organize → synthesize)
4. Use any helper scripts with absolute paths

Remember: Skills are tools to make you more capable and consistent. When in doubt, check if a skill exists for the task!
"""


import logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("subagent_debug")


class SkillsMiddleware(AgentMiddleware):
    """Middleware for loading and exposing agent skills.

    This middleware implements Anthropic's agent skills pattern:
    - Loads skills metadata (name, description) from YAML frontmatter at session start
    - Injects skills list into system prompt for discoverability
    - Agent reads full SKILL.md content when a skill is relevant (progressive disclosure)

    Supports both user-level and project-level skills:
    - User skills: ~/.deepagents/{AGENT_NAME}/skills/
    - Project skills: {PROJECT_ROOT}/.deepagents/skills/
    - Project skills override user skills with the same name

    Args:
        skills_dir: Path to the user-level skills directory (per-agent).
        assistant_id: The agent identifier for path references in prompts.
        project_skills_dir: Optional path to project-level skills directory.
    """

    state_schema = SkillsState

    def __init__(
        self,
        *,
        skills_dir: str | Path,
        assistant_id: str = "agent",
        project_skills_dir: str | Path | None = None,
        name: str = "agent"
    ) -> None:
        """Initialize the skills middleware.

        Args:
            skills_dir: Path to the user-level skills directory.
            assistant_id: The agent identifier.
            project_skills_dir: Optional path to the project-level skills directory.
        """
        self.skills_dir = Path(skills_dir).expanduser()
        self.assistant_id = assistant_id
        self.project_skills_dir = (
            Path(project_skills_dir).expanduser() if project_skills_dir else None
        )
        self.user_skills_display = f"~/.deepagents/{assistant_id}/skills"
        self.system_prompt_template = SKILLS_SYSTEM_PROMPT

        self.agent_name = name
        self.call_count = 0

    def _format_skills_locations(self) -> str:
        """Format skills locations for display in system prompt."""
        locations = [f"**User Skills**: `{self.user_skills_display}`"]
        if self.project_skills_dir:
            locations.append(
                f"**Project Skills**: `{self.project_skills_dir}` (overrides user skills)"
            )
        return "\n".join(locations)

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skills metadata for display in system prompt."""
        if not skills:
            locations = [f"{self.user_skills_display}/"]
            if self.project_skills_dir:
                locations.append(f"{self.project_skills_dir}/")
            return f"(No skills available yet. You can create skills in {' or '.join(locations)})"

        user_skills = [s for s in skills if s["source"] == "user"]
        project_skills = [s for s in skills if s["source"] == "project"]

        lines = []

        if user_skills:
            lines.append("**User Skills:**")
            for skill in user_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")
            lines.append("")

        if project_skills:
            lines.append("**Project Skills:**")
            for skill in project_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")

        return "\n".join(lines)

    def before_agent(self, state: SkillsState, runtime: Runtime) -> SkillsStateUpdate | None:
        """Load skills metadata before agent execution.

        This runs once at session start to discover available skills from both
        user-level and project-level directories.

        Args:
            state: Current agent state.
            runtime: Runtime context.

        Returns:
            Updated state with skills_metadata populated.
        """
        logger.info(f"[{self.agent_name}] 开始调用 before_agent 函数")
        skills = list_skills(
            user_skills_dir=self.skills_dir,
            project_skills_dir=self.project_skills_dir,
        )
        logger.info(f"[{self.agent_name}] 技能扫描完成 - 发现 {len(skills)} 个技能")
        if skills:
            skill_names = [skill['name'] for skill in skills]
            logger.debug(f"[{self.agent_name}] 技能列表: {skill_names}")
        return SkillsStateUpdate(skills_metadata=skills)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject skills documentation into the system prompt.

        This runs on every model call to ensure skills info is always available.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        logger.info(f"[{self.agent_name}] 开始调用 wrap_model_call 函数")
        skills_metadata = request.state.get("skills_metadata", [])

        skills_locations = self._format_skills_locations()
        logger.debug(f"[{self.agent_name}] 技能位置信息: {skills_locations}")
        skills_list = self._format_skills_list(skills_metadata)

        skills_section = self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        """记录模型调用"""
        self.call_count += 1
        logger.info(f"[{self.agent_name}] 第{self.call_count}次模型调用")
        logger.debug(f"[{self.agent_name}] System message: {request.system_message.content[:200] if request.system_message else 'None'}...")
        logger.debug(f"[{self.agent_name}] Messages: {request.messages}")
        
        response = handler(request.override(system_prompt=system_prompt))
        
        logger.info(f"[{self.agent_name}] 模型响应完成")
        logger.debug(f"[{self.agent_name}] Response: {response}")

        return response

    def after_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        """记录模型响应后的状态"""
        logger.info(f"[{self.agent_name}] 开始调用 after_model 函数")
        logger.info(f"[{self.agent_name}] after_model - 消息数量: {len(state.get('messages', []))}")
        # 检查是否有工具调用
        messages = state.get('messages', [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                tool_calls_info = []
                for tc in last_message.tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    tool_args = tc.get('args', {})
                    tool_calls_info.append(f"{tool_name}({tool_args})")
                logger.info(f"[{self.agent_name}] 工具调用: {tool_calls_info}")
        return {}

    def wrap_tool_call(
        self,
        request: Any,
        handler: callable,
    ) -> Any:
        """记录工具调用"""
        logger.info(f"[{self.agent_name}] 开始调用 wrap_tool_call 函数")
        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})
        logger.info(f"[{self.agent_name}] 工具调用: {tool_name}")
        logger.debug(f"[{self.agent_name}] 工具参数: {tool_args}")
        
        result = handler(request)
        
        logger.info(f"[{self.agent_name}] 工具完成: {tool_name}")
        logger.debug(f"[{self.agent_name}] 工具结果: {result}")
        
        return result


class NoSkillsMiddleware(AgentMiddleware):
    """Middleware for subagents without skills loading."""
    
    def __init__(self, name: str = "no-skills-subagent"):
        super().__init__()
        self.agent_name = name
        self.call_count = 0
        self.DONE_WRITE_FILE = False

    def before_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        logger.info(f"[{self.agent_name}] 开始调用 before_agent 函数")
        return super().before_agent(state, runtime)

    def before_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        logger.info(f"[{self.agent_name}] 开始调用 before_model 函数")
        return super().before_model(state, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: callable,
    ) -> ModelResponse:
        """记录模型调用"""
        logger.info(f"[{self.agent_name}] 开始调用 wrap_model_call 函数")
        self.call_count += 1
        logger.info(f"[{self.agent_name}] 第{self.call_count}次模型调用")
        logger.debug(f"[{self.agent_name}] System message: {request.system_message.content[:200] if request.system_message else 'None'}...")
        logger.debug(f"[{self.agent_name}] Messages: {request.messages}")

        response = handler(request)

        logger.info(f"[{self.agent_name}] 模型响应完成")
        logger.debug(f"[{self.agent_name}] Response: {response}")

        # write_file完成后不再调用工具
        if self.DONE_WRITE_FILE == True: 
            response.result[0].tool_calls = []
        if response.result[0].tool_calls:
            if response.result[0].tool_calls[0].get("name") == "write_file":
                self.DONE_WRITE_FILE = True

        return response

    def after_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        """记录模型响应后的状态"""
        logger.info(f"[{self.agent_name}] after_model - 消息数量: {len(state.get('messages', []))}")
        messages = state.get('messages', [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                logger.info(f"[{self.agent_name}] 工具调用: {[tc.get('name') for tc in last_message.tool_calls]}")
        return {}

    def wrap_tool_call(
        self,
        request: Any,
        handler: callable,
    ) -> Any:
        """记录工具调用"""
        logger.info(f"[{self.agent_name}] 开始调用 wrap_tool_call 函数")
        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})
        logger.info(f"[{self.agent_name}] 工具调用: {tool_name}")
        logger.debug(f"[{self.agent_name}] 工具参数: {tool_args}")
        
        result = handler(request)
        
        logger.info(f"[{self.agent_name}] 工具完成: {tool_name}")
        logger.debug(f"[{self.agent_name}] 工具结果: {result}")
        
        return result

    def after_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        logger.info(f"[{self.agent_name}] 开始调用 after_agent 函数")
        return super().after_agent(state, runtime)


__all__ = ["SkillsMiddleware", "NoSkillsMiddleware", "SkillsState", "SkillsStateUpdate"]
