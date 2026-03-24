"""Nodes for deep research graph."""

from __future__ import annotations

import asyncio
from typing import Dict, Any

from deepagents import SubAgent, create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import MessagesState

from kardcraft.llm.discovery import get_model
from kardcraft.tools.error_processor import ErrorProcessor
from kardcraft.utils.logger import logger

from .prompt import (
    get_main_system_prompt,
    get_researcher_system_prompt,
)
from .tools import get_research_tools


async def run_deep_research(state: MessagesState) -> Dict[str, Any]:
    query = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            query = str(msg.content or "").strip()
            break
    if not query:
        return {"messages": [AIMessage(content="")]}

    model_name, temperature = get_model(intent="agent", temperature=0.0)
    base_model = model_name.split("/", 1)[-1] if "/" in model_name else model_name
    model = init_chat_model(model=base_model, temperature=temperature)

    tools = get_research_tools()
    subagent = SubAgent(
        name="researcher",
        description="Research one focused topic and return concise findings.",
        system_prompt=get_researcher_system_prompt(),
        tools=tools,
    )
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=get_main_system_prompt(),
        subagents=[subagent],
    )

    result = None
    last_error = None
    for attempt in range(1, 4):
        try:
            result = await agent.ainvoke({"messages": [("user", query)]})
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            processed = ErrorProcessor.process_llm_error(exc)
            logger.warning(
                "deep_research_graph retry",
                attempt=attempt,
                error_type=processed.error_type,
                error_message=processed.message,
            )
            if attempt < 3:
                await asyncio.sleep(1.5 * attempt)

    content = ""
    if result and isinstance(result, dict) and result.get("messages"):
        last = result["messages"][-1]
        content = str(getattr(last, "content", last) or "").strip()
    elif result:
        content = str(result).strip()
    elif last_error is not None:
        processed = ErrorProcessor.process_llm_error(last_error)
        content = f"deep_research_failed: {processed.message}"

    return {"messages": [AIMessage(content=content)]}
