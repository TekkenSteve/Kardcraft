"""Prompt management for Syllabus Agent."""

from pathlib import Path
from typing import Dict, Tuple, Type

import dspy

from kardcraft.agent_skills import list_skills
from kardcraft.dspy_langfuse import PromptResolver, ResolvedPrompt
from .signature import (
    PROMPT_SCHEMA_VERSION,
    PROMPT_NAMES,
    build_context_sufficiency_signature,
    build_outline_chunk_extraction_signature,
    build_outline_merge_signature,
    build_syllabus_generation_signature,
)


def load_principle_skills(subject_domain: str = "all"):
    """加载适用的原则skills"""
    try:
        skills_dir = (
            Path(__file__).parent.parent.parent.parent.parent.parent
            / ".deepagents"
            / "skills"
        )
        all_skills = list_skills(project_skills_dir=skills_dir)

        principle_skills = [s for s in all_skills if s["name"].startswith("principle-")]

        return principle_skills
    except Exception:
        return []


class ConceptExtractionPrompt(dspy.Module):
    """DSPy module for extracting concepts from content."""

    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(
            "content, subject_domain -> concepts, relationships"
        )

    def forward(self, content: str, subject_domain: str = "general"):
        return self.extract(content=content, subject_domain=subject_domain)


class DependencyAnalysisPrompt(dspy.Module):
    """DSPy module for analyzing concept dependencies."""

    def __init__(self):
        super().__init__()
        self.analyze = dspy.ChainOfThought(
            "concepts, subject_domain -> dependencies, difficulty_levels, prerequisites"
        )

    def forward(self, concepts: str, subject_domain: str = "general"):
        return self.analyze(concepts=concepts, subject_domain=subject_domain)


class PromptManager:
    """Manages prompts for syllabus generation."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.principle_skills = load_principle_skills()
        self.resolver = PromptResolver(prompt_label="production")
        self._last_resolved: Dict[str, ResolvedPrompt] = {}

    def _format_principles_for_prompt(self, principles) -> str:
        """Format principles for prompt."""
        if not principles:
            return ""
        lines = ["## Principles:\n"]
        for p in principles:
            name = p.get("name", "")
            description = p.get("description", "")
            lines.append(f"- **{name}**: {description}")
        return "\n".join(lines)

    def get_concept_extraction_prompt(self, subject_domain: str = "general") -> str:
        """Get concept extraction prompt with subject-specific principles."""

        principles_text = self._format_principles_for_prompt(self.principle_skills)

        base_prompt = """You are an expert educator creating a knowledge dependency graph.

{principles}

## Task:
1. Identify 5-15 core concepts from the content
2. For each concept, determine:
   - Clear, concise title
   - Brief description (1-2 sentences)
   - Difficulty level (basic/intermediate/advanced)
   - Prerequisites (which other concepts must be learned first)

## Output Format:
Return a JSON object with:
```json
{
  "concepts": [
    {
      "id": "concept_1",
      "title": "Concept Title",
      "description": "Brief description",
      "difficulty": "basic|intermediate|advanced",
      "prerequisites": ["prerequisite_concept_id"]
    }
  ],
  "relationships": [
    {
      "from": "concept_1",
      "to": "concept_2", 
      "type": "prerequisite|builds_on|related"
    }
  ]
}
```

## Guidelines:
- Concepts should be atomic (one main idea each)
- Prerequisites should form a valid dependency graph (no cycles)
- Start with foundational concepts, build up complexity
- Use clear, learner-friendly language"""

        return base_prompt.format(principles=principles_text)

    def get_dependency_analysis_prompt(self, subject_domain: str = "general") -> str:
        """Get dependency analysis prompt."""

        return """You are an expert at analyzing knowledge dependencies and learning sequences.

Given a list of concepts, create an optimal learning path by:

1. **Dependency Analysis**: Identify which concepts depend on others
2. **Difficulty Assessment**: Evaluate cognitive load and complexity
3. **Learning Path**: Create a logical sequence for mastery

## Dependency Rules:
- Basic concepts have no prerequisites
- Intermediate concepts build on 1-2 basic concepts
- Advanced concepts may require multiple prerequisites
- No circular dependencies allowed

## Difficulty Factors:
- Abstract vs concrete concepts
- Number of new terms introduced
- Cognitive complexity
- Prior knowledge assumptions

## Output Format:
```json
{
  "dependency_graph": {
    "concept_id": ["dependent_concept_1", "dependent_concept_2"]
  },
  "topological_order": ["concept_1", "concept_2", "concept_3"],
  "learning_levels": {
    "0": ["basic_concept_1", "basic_concept_2"],
    "1": ["intermediate_concept_1"],
    "2": ["advanced_concept_1"]
  },
  "estimated_times": {
    "concept_id": 15  // minutes to master
  }
}
```

Ensure the topological order respects all dependencies."""

    def get_learning_path_prompt(self) -> str:
        """Get learning path optimization prompt."""

        return """Create optimal learning paths from the knowledge dependency graph.

## Objectives:
1. Minimize cognitive load at each step
2. Ensure prerequisites are met before advancing
3. Group related concepts for better retention
4. Provide multiple paths for different learning styles

## Path Types:
- **Linear Path**: Step-by-step progression (good for beginners)
- **Parallel Paths**: Multiple concepts can be learned simultaneously
- **Spiral Path**: Revisit concepts at increasing depth

## Output Format:
```json
{
  "paths": [
    {
      "name": "Foundation Path",
      "description": "Core concepts first",
      "sequence": ["concept_1", "concept_2", "concept_3"],
      "estimated_time": 45,
      "difficulty": "beginner"
    }
  ],
  "milestones": [
    {
      "level": 1,
      "concepts": ["concept_1", "concept_2"],
      "description": "Basic understanding achieved"
    }
  ]
}
```"""

    def get_syllabus_generation_prompt(self) -> str:
        """Get single-pass syllabus generation prompt."""
        prompt, _, _ = self.resolve_syllabus_generation_prompt()
        return prompt

    def _default_syllabus_generation_prompt(self) -> str:
        principles_text = self._format_principles_for_prompt(self.principle_skills)
        return """You are a Syllabus Processor responsible for analyzing course content and extracting its weekly topics and schedule.

{principles}

## Task:
Analyze the following content and extract a structured list of chapters.
Each chapter should have:
- A clear, concise title
- A brief introduction/description
- Estimated difficulty level
- Estimated learning time (in minutes)

## Output Format:
Return a JSON array of chapters:
```json
[
  {{
    "id": "chapter_1",
    "title": "Chapter Title",
    "description": "Brief introduction of this chapter's content",
    "difficulty": "basic|intermediate|advanced",
    "estimated_time": 30
  }},
  ...
]
```

## Guidelines:
- Aim for 4-8 chapters for a complete course
- Start with foundational topics, progress to advanced
- Each chapter should cover a coherent unit of content
- Ensure logical progression between chapters
- Total course should be reasonable for a semester (typically 8-16 weeks)""".format(principles=principles_text)

    def resolve_syllabus_generation_prompt(
        self,
    ) -> Tuple[str, Dict[str, str], Type[dspy.Signature]]:
        resolved = self._resolve_prompt(
            prompt_key="syllabus_generation",
            local_default_prompt=self._default_syllabus_generation_prompt(),
        )
        signature = build_syllabus_generation_signature(resolved.text)
        return resolved.text, self._to_meta_dict(resolved), signature

    def get_context_sufficiency_prompt(self) -> str:
        """Prompt to let LLM judge whether current context is enough."""
        prompt, _, _ = self.resolve_context_sufficiency_prompt()
        return prompt

    def _default_context_sufficiency_prompt(self) -> str:
        return """You are an academic planner.

Assess whether the provided material is sufficient to generate a high-quality learning outline.

Return strict JSON:
{
  "is_sufficient": true or false,
  "reason": "short rationale",
  "missing_aspects": ["..."],
  "retrieval_queries": ["query 1", "query 2", "query 3"]
}

Rules:
- Prefer semantic judgment, not keyword matching.
- retrieval_queries must be short and language-agnostic.
- If sufficient, retrieval_queries can be an empty array."""

    def resolve_context_sufficiency_prompt(
        self,
    ) -> Tuple[str, Dict[str, str], Type[dspy.Signature]]:
        resolved = self._resolve_prompt(
            prompt_key="context_sufficiency",
            local_default_prompt=self._default_context_sufficiency_prompt(),
        )
        signature = build_context_sufficiency_signature(resolved.text)
        return resolved.text, self._to_meta_dict(resolved), signature

    def get_outline_chunk_extraction_prompt(self) -> str:
        """Prompt for map-step outline extraction on a single chunk."""
        prompt, _, _ = self.resolve_outline_chunk_extraction_prompt()
        return prompt

    def _default_outline_chunk_extraction_prompt(self) -> str:
        principles_text = self._format_principles_for_prompt(self.principle_skills)
        return f"""You are extracting a course outline from a partial chunk of source material.

{principles_text}

Task:
1. Extract 3-8 candidate learning units from this chunk.
2. Each unit should be meaningful, teachable, and not too broad.
3. Capture prerequisite dependencies where clear.
4. Keep the original semantic focus of the chunk (do not invent unrelated content).

Return strict JSON:
{{
  "learning_units": [
    {{
      "id": "unit_1",
      "title": "Unit title",
      "content_summary": "1-2 sentence summary",
      "key_concepts": ["concept A", "concept B"],
      "difficulty": "basic|intermediate|advanced",
      "estimated_time": 30,
      "prerequisites": ["unit_0 or prerequisite title"]
    }}
  ]
}}"""

    def resolve_outline_chunk_extraction_prompt(
        self,
    ) -> Tuple[str, Dict[str, str], Type[dspy.Signature]]:
        resolved = self._resolve_prompt(
            prompt_key="outline_chunk_extraction",
            local_default_prompt=self._default_outline_chunk_extraction_prompt(),
        )
        signature = build_outline_chunk_extraction_signature(resolved.text)
        return resolved.text, self._to_meta_dict(resolved), signature

    def get_outline_merge_prompt(self) -> str:
        """Prompt for reduce-step global merge and ordering."""
        prompt, _, _ = self.resolve_outline_merge_prompt()
        return prompt

    def _default_outline_merge_prompt(self) -> str:
        principles_text = self._format_principles_for_prompt(self.principle_skills)
        return f"""You are consolidating multiple partial outline candidates into one final syllabus.

{principles_text}

Task:
1. Merge duplicates and overlaps across chunks.
2. Produce a coherent learning progression from foundations to advanced topics.
3. Keep 4-12 units in total.
4. Use stable unit ids like unit_1, unit_2, ...
5. Ensure prerequisites only reference existing unit ids in final output.

Return strict JSON:
{{
  "learning_units": [
    {{
      "id": "unit_1",
      "title": "Unit title",
      "content_summary": "1-2 sentence summary",
      "key_concepts": ["..."],
      "difficulty": "basic|intermediate|advanced",
      "estimated_time": 30,
      "prerequisites": ["unit_0"]
    }}
  ]
}}"""

    def resolve_outline_merge_prompt(
        self,
    ) -> Tuple[str, Dict[str, str], Type[dspy.Signature]]:
        resolved = self._resolve_prompt(
            prompt_key="outline_merge",
            local_default_prompt=self._default_outline_merge_prompt(),
        )
        signature = build_outline_merge_signature(resolved.text)
        return resolved.text, self._to_meta_dict(resolved), signature

    def _resolve_prompt(self, prompt_key: str, local_default_prompt: str) -> ResolvedPrompt:
        prompt_name = PROMPT_NAMES[prompt_key]
        resolved = self.resolver.resolve(
            module_name=prompt_name,
            lang=self.lang,
            local_default_prompt=local_default_prompt,
            expected_schema_version=PROMPT_SCHEMA_VERSION,
        )
        self._last_resolved[prompt_key] = resolved
        return resolved

    def _to_meta_dict(self, resolved: ResolvedPrompt) -> Dict[str, str]:
        return {
            "source": resolved.source,
            "name": resolved.prompt_name,
            "label": resolved.prompt_label,
            "version": resolved.prompt_version,
            "schema_version": resolved.schema_version,
            "hash": resolved.prompt_hash,
        }
