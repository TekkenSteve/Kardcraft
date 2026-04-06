"""Nodes for Syllabus Agent."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langgraph.runtime import Runtime

from kardcraft.llm.client import chat_complete
from kardcraft.llm import get_model
from kardcraft.tools.clarification_tools import generate_clarification_questions
from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.tools.web_search_tools import quick_research
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger
from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.workflow.graphs.main_graph.state import Context

from .prompt import PromptManager
from .state import State
from .utils import (
    build_outline_source_chunks,
    normalize_learning_units,
    parse_learning_units_from_response,
)

langfuse = get_langfuse_client()


def _record_prompt_resolution(prompt_meta: Dict[str, Any]) -> None:
    """Record prompt resolution metadata for auditability."""
    try:
        langfuse.event(
            name="syllabus_agent.prompt_resolved",
            metadata=prompt_meta,
        )
    except Exception as exc:
        logger.warning("Failed to record syllabus prompt resolution", error=str(exc))


def _attach_signature_meta(
    prompt_meta: Dict[str, Any],
    signature_cls: Any,
) -> Dict[str, Any]:
    meta = dict(prompt_meta)
    meta["signature_contract"] = getattr(signature_cls, "__name__", "unknown")
    return meta


def _build_assessment_input(
    user_input: str,
    subject_domain: str,
    user_knowledge: str,
    retrieved_context: List[Dict[str, Any]],
) -> str:
    context_preview = "\n\n".join(
        [
            f"[{ctx.get('store', 'unknown')}] {ctx.get('content', '')[:1000]}"
            for ctx in retrieved_context[:3]
        ]
    )
    return (
        f"User Input:\n{user_input}\n\n"
        f"Subject Domain:\n{subject_domain}\n\n"
        f"User Knowledge:\n{user_knowledge[:2000]}\n\n"
        f"Retrieved Context Preview:\n{context_preview}"
    )


def _build_default_queries(user_input: str, subject_domain: str) -> List[str]:
    base = f"{subject_domain} {user_input}".strip()
    queries = [base]
    if user_input:
        queries.append(user_input.strip())
    if subject_domain:
        queries.append(f"{subject_domain} syllabus")
    return [query for query in queries if query]


async def _llm_generate_text(
    model_name: str,
    temperature: float,
    system_prompt: str,
    user_message: str,
    *,
    intent: str = "think",
) -> str:
    try:
        response = await chat_complete(
            intent=intent,
            model=model_name,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        if not response or not hasattr(response, "choices") or not response.choices:
            return ""

        message = response.choices[0].message
        return getattr(message, "content", "") or ""
    except Exception as exc:
        logger.warning("Syllabus LLM completion failed", error=str(exc))
        return ""


async def _assess_and_enrich_context(
    state: State,
    retrieved_context: List[Dict[str, Any]],
    rag_queries: List[Dict[str, Any]],
    session_id: str | None,
    user_id: str | None,
) -> Dict[str, Any]:
    """Use LLM judgement to decide whether more context retrieval is needed."""
    user_input = state.get("user_input", "")
    user_knowledge = state.get("user_knowledge", "")
    subject_domain = state.get("subject_domain", "general")
    file_ids = state.get("file_ids")
    normalized_file_ids = [str(fid).strip() for fid in (file_ids or []) if str(fid).strip()]
    iteration = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 3)

    prompt_manager = PromptManager(lang=str(state.get("language", "en")))
    model_name, temperature = get_model("think")

    should_attempt_retrieval = iteration < max_iterations
    if not should_attempt_retrieval:
        return {
            "retrieved_context": retrieved_context,
            "rag_queries": rag_queries,
        }

    # File-driven hard signal: fetch at least one query directly tied to user intent
    # before any LLM-generated retrieval query planning.
    if normalized_file_ids and user_id and not retrieved_context:
        seed_queries: List[str] = []
        if user_input.strip():
            seed_queries.append(user_input.strip())
        seed_queries.append("Extract the questions, key knowledge points, and reference answers from the uploaded file")

        for query in seed_queries:
            try:
                kg_result = await query_knowledge.ainvoke(
                    {
                        "query": query,
                        "mode": "mix",
                        "top_k": 8,
                        "session_id": session_id,
                        "file_ids": normalized_file_ids,
                        "user_id": user_id,
                    }
                )
            except Exception as exc:
                logger.warning("Seed knowledge retrieval failed", query=query, error=str(exc))
                continue

            if not isinstance(kg_result, dict):
                logger.warning(
                    "Seed knowledge retrieval returned non-dict result",
                    result_type=type(kg_result).__name__,
                )
                continue

            rag_queries.append(
                {
                    "query": query,
                    "mode": "mix",
                    "store": "knowledge_base",
                }
            )
            content = kg_result.get("content", "")
            if content:
                retrieved_context.append(
                    {
                        "store": "knowledge_base",
                        "content": content,
                        "refs": kg_result.get("refs", []),
                    }
                )

            # A single strong file hit is enough as seed context.
            if content and len(content) > 300:
                break

    assessment_message = _build_assessment_input(
        user_input=user_input,
        subject_domain=subject_domain,
        user_knowledge=user_knowledge,
        retrieved_context=retrieved_context,
    )

    system_prompt, prompt_meta, signature_cls = (
        prompt_manager.resolve_context_sufficiency_prompt()
    )
    _record_prompt_resolution(_attach_signature_meta(prompt_meta, signature_cls))

    assessment_raw = await _llm_generate_text(
        model_name=model_name,
        temperature=temperature,
        system_prompt=system_prompt,
        user_message=assessment_message,
    )
    assessment = safe_parse_llm_json(assessment_raw, default={})
    if not isinstance(assessment, dict):
        assessment = {}
    is_sufficient = bool(assessment.get("is_sufficient", False))

    if is_sufficient:
        return {
            "retrieved_context": retrieved_context,
            "rag_queries": rag_queries,
        }

    llm_queries = assessment.get("retrieval_queries", [])
    retrieval_queries = [
        query.strip()
        for query in llm_queries
        if isinstance(query, str) and query.strip()
    ]
    if file_ids and user_input.strip():
        retrieval_queries = [user_input.strip()] + retrieval_queries
    if not retrieval_queries:
        retrieval_queries = _build_default_queries(user_input, subject_domain)

    for query in retrieval_queries[:3]:
        try:
            kg_result = await query_knowledge.ainvoke(
                {
                    "query": query,
                    "mode": "mix",
                    "top_k": 5,
                    "session_id": session_id,
                    "file_ids": normalized_file_ids,
                    "user_id": user_id,
                }
            )
        except Exception as exc:
            logger.warning("Knowledge retrieval failed", query=query, error=str(exc))
            continue

        if not isinstance(kg_result, dict):
            logger.warning(
                "Knowledge retrieval returned non-dict result",
                result_type=type(kg_result).__name__,
            )
            continue

        rag_queries.append(
            {
                "query": query,
                "mode": "mix",
                "store": "knowledge_base",
            }
        )

        content = kg_result.get("content", "")
        if content:
            retrieved_context.append(
                {
                    "store": "knowledge_base",
                    "content": content,
                    "refs": kg_result.get("refs", []),
                }
            )

    if retrieved_context:
        return {
            "retrieved_context": retrieved_context,
            "rag_queries": rag_queries,
        }

    try:
        web_result = await quick_research.ainvoke(
            {
                "query": retrieval_queries[0] if retrieval_queries else subject_domain,
                "max_results": 3,
            }
        )
        rag_queries.append(
            {
                "query": retrieval_queries[0] if retrieval_queries else subject_domain,
                "mode": "web",
                "store": "web_search",
            }
        )
        if isinstance(web_result, dict) and web_result.get("results"):
            web_content = "\n\n".join(
                [
                    f"## {item.get('title', 'Untitled')}\n{item.get('content', '')}"
                    for item in web_result.get("results", [])
                ]
            )
            retrieved_context.append(
                {
                    "store": "web_search",
                    "content": web_content,
                    "results": web_result.get("results", []),
                }
            )
    except Exception as exc:
        logger.warning("Web retrieval failed", error=str(exc))

    return {
        "retrieved_context": retrieved_context,
        "rag_queries": rag_queries,
    }


async def _extract_partial_units(
    chunks: List[Dict[str, Any]],
    user_input: str,
    subject_domain: str,
    complexity_level: str,
    language: str = "en",
) -> List[Dict[str, Any]]:
    if not chunks:
        return []

    prompt_manager = PromptManager(lang=language)
    model_name, temperature = get_model("think")
    system_prompt, prompt_meta, signature_cls = (
        prompt_manager.resolve_outline_chunk_extraction_prompt()
    )
    _record_prompt_resolution(_attach_signature_meta(prompt_meta, signature_cls))

    partial_results: List[Dict[str, Any]] = []
    for chunk in chunks:
        user_message = (
            f"User Input:\n{user_input}\n\n"
            f"Subject Domain:\n{subject_domain}\n\n"
            f"Complexity Level:\n{complexity_level}\n\n"
            f"Chunk ID:\n{chunk['chunk_id']}\n\n"
            f"Chunk Content:\n{chunk['content']}"
        )
        raw_response = await _llm_generate_text(
            model_name=model_name,
            temperature=temperature,
            system_prompt=system_prompt,
            user_message=user_message,
        )
        units, _ = parse_learning_units_from_response(raw_response)
        if units:
            partial_results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "learning_units": units,
                }
            )

    return partial_results


async def _merge_partial_units(
    partial_results: List[Dict[str, Any]],
    user_input: str,
    subject_domain: str,
    complexity_level: str,
    language: str = "en",
) -> Dict[str, Any]:
    prompt_manager = PromptManager(lang=language)
    model_name, temperature = get_model("think")

    system_prompt, prompt_meta, signature_cls = prompt_manager.resolve_outline_merge_prompt()
    _record_prompt_resolution(_attach_signature_meta(prompt_meta, signature_cls))
    user_message = (
        f"User Input:\n{user_input}\n\n"
        f"Subject Domain:\n{subject_domain}\n\n"
        f"Complexity Level:\n{complexity_level}\n\n"
        f"Partial Candidates JSON:\n{json.dumps(partial_results, ensure_ascii=False)}"
    )
    merged_raw = await _llm_generate_text(
        model_name=model_name,
        temperature=temperature,
        system_prompt=system_prompt,
        user_message=user_message,
    )
    units, metadata = parse_learning_units_from_response(merged_raw)
    return {
        "units": units,
        "raw": merged_raw,
        "metadata": metadata,
    }


async def _single_pass_fallback(
    user_input: str,
    subject_domain: str,
    complexity_level: str,
    user_knowledge: str,
    retrieved_context: List[Dict[str, Any]],
    language: str = "en",
) -> Dict[str, Any]:
    prompt_manager = PromptManager(lang=language)
    model_name, temperature = get_model("think")
    system_prompt, prompt_meta, signature_cls = (
        prompt_manager.resolve_syllabus_generation_prompt()
    )
    _record_prompt_resolution(_attach_signature_meta(prompt_meta, signature_cls))
    chunks = build_outline_source_chunks(
        user_input=user_input,
        subject_domain=subject_domain,
        user_knowledge=user_knowledge,
        retrieved_context=retrieved_context,
        max_chunk_chars=12000,
        overlap_chars=0,
    )
    source_text = chunks[0]["content"] if chunks else ""

    user_message = (
        f"User Input:\n{user_input}\n\n"
        f"Subject Domain:\n{subject_domain}\n\n"
        f"Complexity Level:\n{complexity_level}\n\n"
        f"Source:\n{source_text}"
    )
    raw_response = await _llm_generate_text(
        model_name=model_name,
        temperature=temperature,
        system_prompt=system_prompt,
        user_message=user_message,
    )
    units, metadata = parse_learning_units_from_response(raw_response)
    return {
        "units": units,
        "raw": raw_response,
        "metadata": metadata,
    }


async def init_syllabus(state: State) -> Dict[str, Any]:
    """Initialize syllabus state on first run."""
    existing_draft = state.get("syllabus_draft", "")
    existing_units = state.get("learning_units", [])
    if existing_draft or existing_units:
        logger.info(
            "Resuming syllabus agent with existing state",
            draft_length=len(existing_draft),
            unit_count=len(existing_units),
        )
        return {}

    logger.info(
        "Initializing syllabus agent",
        file_count=len(state.get("file_ids", []) or []),
        has_query=bool(state.get("user_input")),
    )

    return {
        "rag_queries": [],
        "retrieved_context": [],
        "syllabus_draft": "",
        "learning_units": [],
        "approved_unit_ids": [],
        "pending_questions": [],
        "clarification_responses": {},
        "iteration_count": 0,
        "max_iterations": 3,
    }


async def generate_syllabus(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    """Generate a syllabus outline via map-reduce style LLM extraction."""
    context = runtime.context
    session_id = context.session_id if context else None
    user_id = context.user_id if context else None
    user_input = state.get("user_input", "")
    user_knowledge = state.get("user_knowledge") or ""
    subject_domain = state.get("subject_domain", "general") or "general"
    complexity_level = state.get("complexity_level")
    language = state.get("language", "en")
    retrieved_context = list(state.get("retrieved_context", []))
    rag_queries = list(state.get("rag_queries", []))

    logger.info(
        "Generating syllabus outline",
        query_length=len(user_input),
        knowledge_length=len(user_knowledge),
        context_count=len(retrieved_context),
    )

    try:
        context_result = await _assess_and_enrich_context(
            state=state,
            retrieved_context=retrieved_context,
            rag_queries=rag_queries,
            session_id=session_id,
            user_id=user_id,
        )
        if not isinstance(context_result, dict):
            logger.warning(
                "Context enrichment returned non-dict result; keep existing context",
                result_type=type(context_result).__name__,
            )
        else:
            retrieved_context = list(context_result.get("retrieved_context") or retrieved_context)
            rag_queries = list(context_result.get("rag_queries") or rag_queries)
    except Exception as exc:
        logger.warning("Context enrichment failed, continuing with existing context", error=str(exc))

    if not user_knowledge.strip() and not retrieved_context:
        questions = await generate_clarification_questions.ainvoke(
            {
                "required_info": ["主体学科", "具体学习目标", "已有背景知识"],
                "source_agent": "syllabus_agent",
                "target_object": "Syllabus",
                "context_summary": f"User input: {user_input}",
            }
        )
        return {
            "pending_questions": questions,
            "rag_queries": rag_queries,
            "retrieved_context": retrieved_context,
        }

    chunks = build_outline_source_chunks(
        user_input=user_input,
        subject_domain=subject_domain,
        user_knowledge=user_knowledge,
        retrieved_context=retrieved_context,
    )
    partial_results = await _extract_partial_units(
        chunks=chunks,
        user_input=user_input,
        subject_domain=subject_domain,
        complexity_level=complexity_level,
        language=language,
    )

    merged = {"units": [], "raw": "", "metadata": {}}
    if partial_results:
        merged = await _merge_partial_units(
            partial_results=partial_results,
            user_input=user_input,
            subject_domain=subject_domain,
            complexity_level=complexity_level,
            language=language,
        )

    units = merged["units"]
    draft = merged["raw"]

    if not units:
        fallback = await _single_pass_fallback(
            user_input=user_input,
            subject_domain=subject_domain,
            complexity_level=complexity_level,
            user_knowledge=user_knowledge,
            retrieved_context=retrieved_context,
            language=language,
        )
        units = fallback["units"]
        draft = fallback["raw"]

    if not units and partial_results:
        flattened = []
        for result in partial_results:
            flattened.extend(result.get("learning_units", []))
        units = normalize_learning_units(flattened)

    if not units:
        return {
            "syllabus_draft": draft,
            "learning_units": [],
            "retrieved_context": retrieved_context,
            "rag_queries": rag_queries,
            "error": "Unable to extract syllabus outline from current material.",
        }

    logger.info("Syllabus outline generated", unit_count=len(units))
    return {
        "syllabus_draft": draft,
        "learning_units": units,
        "retrieved_context": retrieved_context,
        "rag_queries": rag_queries,
        "approved_unit_ids": [],
        "pending_questions": [],
    }


async def request_feedback(state: State) -> Dict[str, Any]:
    """Auto-approve units until human-in-the-loop is wired in main flow."""
    learning_units = state.get("learning_units", [])
    iteration = state.get("iteration_count", 0)
    approved_ids = [unit.get("id") for unit in learning_units if unit.get("id")]

    logger.info(
        "Auto-approving syllabus units",
        unit_count=len(learning_units),
        iteration=iteration,
    )
    return {
        "approved_unit_ids": approved_ids,
        "iteration_count": iteration + 1,
    }


async def finalize_syllabus(state: State) -> Dict[str, Any]:
    """Finalize syllabus state output."""
    learning_units = state.get("learning_units", [])
    approved_unit_ids = state.get("approved_unit_ids", [])

    logger.info(
        "Finalizing syllabus",
        units=len(learning_units),
        approved=len(approved_unit_ids),
    )
    return {
        "syllabus_draft": state.get("syllabus_draft", ""),
        "learning_units": learning_units,
        "approved_unit_ids": approved_unit_ids,
        "retrieved_context": state.get("retrieved_context", []),
        "rag_queries": state.get("rag_queries", []),
    }
