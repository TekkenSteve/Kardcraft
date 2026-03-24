# Agent Skills System

这是一个独立的 Agent Skills 实现，用于 Kardcraft 的自定义 LangGraph。

## 设计理念

- **遵循标准**：完全遵循 [Agent Skills 规范](https://agentskills.io/specification)
- **独立实现**：不依赖 DeepAgents 框架，但使用方法相同
- **简单直接**：从 archive/DeepAgents-Skills 复制核心加载逻辑
- **渐进式披露**：只在需要时加载完整 skill 内容

## 与 DeepAgents 的关系

- ✅ 使用相同的 SKILL.md 格式
- ✅ 使用相同的目录结构（.deepagents/skills/）
- ✅ 遵循相同的 Agent Skills 标准
- ✅ 使用方法完全一致
- ❌ 不依赖 DeepAgents 的 create_deep_agent
- ❌ 不使用 DeepAgents 的 middleware
- ✅ 可以在自定义 LangGraph 中使用

## 使用方法

### 1. 加载 Skills

```python
from kardcraft.agent_skills import list_skills
from pathlib import Path

# 加载项目 skills
skills_dir = Path(".deepagents/skills")
skills = list_skills(project_skills_dir=skills_dir)

# 遍历 skills
for skill in skills:
    print(f"Skill: {skill['name']}")
    print(f"Description: {skill['description']}")
    print(f"Path: {skill['path']}")
    print(f"Source: {skill['source']}")
```

### 2. 读取 Skill 内容

```python
from pathlib import Path

# 读取完整的 SKILL.md
skill_path = Path(skill['path'])
content = skill_path.read_text(encoding='utf-8')
```

### 3. 在 LangGraph 中使用

```python
from kardcraft.agent_skills import list_skills

# 在 node 中加载 skills
async def my_node(state):
    skills = list_skills(project_skills_dir=Path(".deepagents/skills"))
    
    # 根据意图匹配 skill
    for skill in skills:
        if "intent" in skill['name'].lower():
            # 使用这个 skill
            skill_content = Path(skill['path']).read_text()
            # ... 处理 skill 内容
    
    return state
```

## Skill 格式

### SKILL.md（标准格式）

```markdown
---
name: intent-clarification
description: Clarify user intent through progressive questioning
---

# Intent Clarification Skill

## When to Use
- User input is ambiguous
- Missing critical information

## Instructions
1. Identify missing information
2. Generate clarification questions
3. Collect user responses
...
```

## 目录结构

```
.deepagents/skills/
├── skill-name-1/
│   ├── SKILL.md          # 必需：技能定义
│   └── ...               # 可选：其他文件
├── skill-name-2/
│   └── SKILL.md
└── ...
```

## API 参考

### `list_skills()`

加载 skills 列表。

**参数：**
- `user_skills_dir` (Path | None): 用户级 skills 目录
- `project_skills_dir` (Path | None): 项目级 skills 目录

**返回：**
- `list[SkillMetadata]`: Skill 元数据列表

### `SkillMetadata`

Skill 元数据类型。

**字段：**
- `name` (str): Skill 名称
- `description` (str): Skill 描述
- `path` (str): SKILL.md 文件路径
- `source` (str): 来源（'user' 或 'project'）

## 来源

从 `archive/DeepAgents-Skills/skills/` 复制而来，保持原有实现。
