"""Clarification Tools - Self-contained tool for generating clarification questions.

By making this a tool, agents can generate questions directly without leaving their subgraph.
"""

import json
import dspy
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from kardcraft.utils.logger import logger
from kardcraft.llm import configure_dspy_lm


class GenerateClarificationQuestions(dspy.Signature):
    """生成反问问题以收集必要信息"""
    
    source_agent: str = dspy.InputField(desc="请求反问的agent名称")
    required_info: str = dspy.InputField(desc="需要收集的信息类型列表（JSON格式）")
    current_context: str = dspy.InputField(desc="当前上下文信息（JSON格式）")
    relevant_skills: str = dspy.InputField(desc="相关的skill指导原则（JSON格式）")
    conversation_history: str = dspy.InputField(desc="对话历史（JSON格式）")
    
    questions: str = dspy.OutputField(
        desc="生成的问题列表（JSON格式），每个问题包含：question_id, question_text, info_type, is_required, suggested_answers"
    )
    reasoning: str = dspy.OutputField(desc="生成这些问题的推理过程")


def _parse_questions(output: str) -> List[Dict[str, Any]]:
    """Helper to parse questions from LLM output."""
    try:
        # Try direct JSON
        data = json.loads(output)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]
    except:
        # Try finding markdown block
        try:
            start = output.find("[")
            end = output.rfind("]") + 1
            if start != -1 and end > start:
                return json.loads(output[start:end])
        except:
            pass
    return []


def _fallback_questions(required_info: List[str]) -> List[Dict[str, Any]]:
    """Fallback templates for common missing info."""
    templates = {
        "主体学科": "您能否确认所属的具体学科领域？",
        "具体学习目标": "您的学习目标是什么？（例如：考试、工作应用、兴趣学习等）",
        "已有背景知识": "您对这个主题有什么已有的了解吗？",
    }
    questions = []
    for i, info in enumerate(required_info):
        text = templates.get(info, f"请提供关于 {info} 的更多详细信息。")
        questions.append({
            "question_id": f"q_{i+1}",
            "question_text": text,
            "info_type": info,
            "is_required": True
        })
    return questions


@tool(parse_docstring=True)
async def generate_clarification_questions(
    required_info: List[str],
    source_agent: str,
    target_object: str = "syllabus",
    context_summary: str = ""
) -> List[Dict[str, Any]]:
    """Generate targeted clarification questions for the user.
    
    Use this tool when you determine that you cannot fulfill a request because 
    specific information is missing from both the user's input and automated research.

    Args:
        required_info: List of information types missing (e.g., ["learning_goals", "depth"])
        source_agent: Name of the agent requesting info (e.g., "syllabus_agent")
        target_object: What is being created (e.g., "syllabus", "concept_map")
        context_summary: Brief summary of what is already known to help frame questions

    Returns:
        List of question dicts, each with:
        - question_id: Unique ID
        - question_text: The actual question for the user
        - info_type: What this question targets
        - is_required: Boolean
    """
    logger.info(
        "generate_clarification_questions tool called",
        source=source_agent,
        missing=required_info,
    )

    try:
        lm = configure_dspy_lm()
        if not lm:
            return _fallback_questions(required_info)

        # Use dspy predictor
        predictor = dspy.Predict(GenerateClarificationQuestions)
        
        result = predictor(
            source_agent=source_agent,
            required_info=json.dumps(required_info, ensure_ascii=False),
            current_context=context_summary,
            relevant_skills="[]",
            conversation_history="[]"
        )
        
        questions = _parse_questions(result.questions)
        if not questions:
            return _fallback_questions(required_info)
            
        return questions

    except Exception as e:
        logger.error("Failed to generate clarification questions via tool", error=str(e))
        return _fallback_questions(required_info)
