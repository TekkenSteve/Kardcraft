"""Shared runtime helpers for LangChain create_agent supervisors."""

from __future__ import annotations

from typing import Any, Dict, Type

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from pydantic import BaseModel

from kardcraft.llm.discovery import get_model
from kardcraft.utils.logger import logger


def get_react_model():
    """Get chat model for create_agent."""
    model_name, _ = get_model("agent")
    try:
        return init_chat_model(model=model_name, temperature=0.0)
    except Exception as exc:
        fallback_model, _ = get_model("fast")
        logger.warning("init_chat_model failed, fallback model", error=str(exc), model=fallback_model)
        return init_chat_model(model=fallback_model, temperature=0.0)


async def run_react_structured(
    *,
    prompt: str,
    tools: list,
    response_schema: Type[BaseModel],
    user_payload: Dict[str, Any],
    name: str,
) -> Dict[str, Any]:
    """Run a react-style agent and return structured response dict."""
    try:
        agent = create_agent(
            model=get_react_model(),
            tools=tools,
            system_prompt=prompt,
            response_format=response_schema,
            name=name,
        )
        result = await agent.ainvoke({"messages": [("user", str(user_payload))]})
    except Exception as exc:
        logger.warning("react agent invocation failed", name=name, error=str(exc))
        return {}
    structured = (
        result.get("structured_response")
        or result.get("output")
        or result.get("response")
    )
    if structured is None:
        return {}
    if isinstance(structured, BaseModel):
        return structured.model_dump()
    if isinstance(structured, dict):
        return structured
    return {}
