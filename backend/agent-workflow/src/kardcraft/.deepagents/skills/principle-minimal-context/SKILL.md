---
name: principle-minimal-context
description: 最小上下文原则 - 题干只保留触发回忆的最小线索，去除无关信息
keywords: [anki, principle, concise, minimal, core]
priority: 85
category: core
applicable_subjects: [all]
applicable_contexts: [all]
---

# 最小上下文 Min Context

## 定义

题干只保留触发回忆的最小线索。

## Agent 规则

```python
if len(question) > 30:
    compress()
```

## 使用时机

- 创建任何卡片时
- 题干过长时
- 包含无关信息时

## Bad 反面案例

长段材料后埋一个填空

**问题:** 阅读负担过大，干扰记忆

## Good 正面案例

填空句只留一个【】

**优点:** 最小线索，快速触发

## 实施要点

- 题干不超过25字（Basic/Cloze）
- IRead 卡可以30-100字
- 去除无关信息
- 保留关键触发词
- 使用简洁表达

## 与其他原则的关系

- **题型守恒**: IR卡允许30-100字，QA/CL仍≤25字
- **无二义性**: 在保持最小的同时确保无歧义
- **原子职责**: 最小上下文是原子职责的延伸
