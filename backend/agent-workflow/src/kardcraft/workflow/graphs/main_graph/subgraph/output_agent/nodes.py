"""Nodes for output agent."""

from __future__ import annotations

from typing import Any, Dict

from langgraph.runtime import Runtime

from kardcraft.workflow.graphs.main_graph.state import Context
from .utils import run_output_generation

from .state import State


async def run_output_agent_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    del runtime
    result = await run_output_generation.ainvoke(
        {
            "cards": state.get("cards") or [],
            "payload": state.get("payload") or {},
        }
    )
    return {"output_cards": result.get("output_cards") or []}
