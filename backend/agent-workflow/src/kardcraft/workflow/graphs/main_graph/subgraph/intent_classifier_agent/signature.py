"""Intent Classification Signature and multilingual instructions."""

import dspy
from functools import lru_cache

PROMPT_NAME = "intent_classification"
PROMPT_SCHEMA_VERSION = "1"

INSTRUCTIONS = {
    "en": """You are a professional flashcard creation request analyst.

Analyze user input and classify:

1. Intent Type (choose one):
   - create_cards: User wants to create new flashcards
   - optimize_cards: User wants to improve existing cards
   - review_cards: User wants to review/study cards
   - analyze_content: User wants content analysis only

2. Content Mode (choose one - THIS IS CRITICAL):
   - content_driven: User provides ACTUAL content (text, document, article, textbook excerpt) that can be analyzed for concepts
   - topic_driven: User provides ONLY a topic/theme without actual content

   Examples of content_driven: "Here is an article about photosynthesis, help me make flashcards", "Here are my Python notes..."
   Examples of topic_driven: "Can you help me make flashcards for Three Kingdoms figures?", "I want to learn quantum mechanics"

3. Subject Domain (choose one or 'general'):
   - mathematics, physics, chemistry, biology
   - languages, literature, history, geography
   - computer_science, engineering
   - medicine, psychology, philosophy
   - business, economics, law
   - general

4. Task Complexity (choose one - based on input scale, NOT content difficulty):
   - simple: Short input, few files, straightforward task
   - medium: Moderate input length or few documents
   - complex: Long input, many documents, multi-part request

5. Language (preferred card/output language):
   - If the user explicitly specifies a language, use that.
   - Otherwise, default to the language of the task/requirement (not the pasted content).
   - Use ISO-style short codes when possible: zh, en, ja, ko, fr, de, es, ru, pt, it, ar.

Respond in JSON format.""",
    "zh": """你是一个专业的闪卡创建请求分析助手。

分析用户输入并分类:

1. Intent Type (choose one):
   - create_cards: 用户想要创建新闪卡
   - optimize_cards: 用户想要优化现有卡片
   - review_cards: 用户想要复习/学习卡片
   - analyze_content: 用户只想要内容分析

2. Content Mode (choose one - THIS IS CRITICAL):
   - content_driven: 用户提供了实际可分析的内容(文章、文档、教材摘录等)
   - topic_driven: 用户只提供了主题/领域，没有具体内容材料

   content_driven例子: "以下是一篇关于光合作用的文章，请帮我制作闪卡", "这是我的Python笔记..."
   topic_driven例子: "你能帮我制作三国人物的闪卡吗?", "我想学习量子力学"

3. Subject Domain (choose one或general):
   - mathematics, physics, chemistry, biology
   - languages, literature, history, geography
   - computer_science, engineering
   - medicine, psychology, philosophy
   - business, economics, law
   - general

4. Task Complexity (choose one - 基于输入规模，而非内容难度):
   - simple: 简短输入，文件少，任务简单
   - medium: 输入长度适中或文档较少
   - complex: 长输入，多文档，复合任务

5. Language (preferred card/output language):
   - 如果用户明确指定使用语言，直接使用该语言
   - 否则，默认使用任务/需求描述的语言（不是粘贴的素材语言）
   - 尽量使用短码: zh, en, ja, ko, fr, de, es, ru, pt, it, ar

响应JSON格式.""",
}


class _IntentClassificationSignature(dspy.Signature):
    """Base signature with field definitions."""

    user_input = dspy.InputField(desc="用户原始输入文本 / User's original input text")
    file_info = dspy.InputField(
        desc="上传文件的元信息(文件名、类型等)，无文件则为空 / File metadata, empty if no file"
    )

    intent_type = dspy.OutputField(
        desc="意图类型 / Intent type: create_cards | optimize_cards | review_cards | analyze_content"
    )
    driven_mode = dspy.OutputField(
        desc="内容模式 / Content mode: content_driven | topic_driven"
    )
    subject_domain = dspy.OutputField(desc="学科领域 / Subject domain")
    task_complexity = dspy.OutputField(
        desc="任务复杂度 / Task complexity: simple | medium | complex (based on input scale)"
    )
    confidence = dspy.OutputField(desc="分类置信度 0.0-1.0 / Classification confidence")
    language = dspy.OutputField(
        desc="卡片语言 / Preferred card language (e.g., zh, en, ja)"
    )
    information_sufficient = dspy.OutputField(
        desc="信息是否足够进入下一阶段 / true | false"
    )
    missing_info_types = dspy.OutputField(
        desc="缺失信息类型列表(JSON数组字符串) / Missing info types in JSON array string"
    )


@lru_cache(maxsize=None)
def _get_signature(lang: str) -> type[dspy.Signature]:
    """Get signature with specified language instructions (cached)."""
    # with_instructions will set the passed instructions as the __doc__ of the new class, so signature.instructions can correctly return the instructions in the corresponding language
    return _IntentClassificationSignature.with_instructions(
        INSTRUCTIONS.get(lang, INSTRUCTIONS["en"])
    )


def build_signature_with_prompt(prompt_text: str) -> type[dspy.Signature]:
    """Bind a resolved runtime prompt to the base signature."""
    return _IntentClassificationSignature.with_instructions(prompt_text)
