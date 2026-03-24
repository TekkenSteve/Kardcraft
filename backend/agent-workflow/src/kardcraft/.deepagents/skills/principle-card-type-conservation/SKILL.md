---
name: principle-card-type-conservation
description: 题型守恒原则 - 在同样记忆目标下，优先选记忆负担最小的题型（IRead/Basic/Cloze/Reverse）
keywords: [anki, principle, card-type, memory-burden, core]
priority: 100
category: core
applicable_subjects: [all]
applicable_contexts: [all]
---

# 题型守恒 Card Type Conservation

## 定义

在同样记忆目标下，优先选记忆负担最小的题型，且一张卡只选一种题型。

## Anki 4种原子题型

| 代号 | 英文名 | 中文名 | 记忆负担 | Agent使用时机 | 模板特征 |
|------|--------|--------|----------|---------------|----------|
| IR | IRead | 阅读题 | 0 | 答案>30字 or 只需眼熟 | 无交互，纯展示 |
| QA | Basic | 简答题 | 1 | 答案≤15字且唯一 | 正面Q，背面A |
| CL | Cloze | 填空题 | 1*n | 句子含≥2个可挖空关键词 | {{c1::关键词}} |
| RC | Reverse | 双向卡 | 2 | 高价值、易混、语言对 | 自动生成正反两张 |

## Agent 规则

```python
if len(answer_tokens) > 30 and recall_strictness == False:
    return "IRead"
elif len(answer_tokens) <= 15 and unique_fact:
    return "Basic"
elif sentence.count(keyword) >= 2:
    return "Cloze"
elif priority > 0.9:
    return ["Basic", "Reverse"]  # 双向
```

## 使用时机

- 创建任何 Anki 卡片时，首先决定题型
- 答案较长（>30字）时，考虑 IRead
- 有多个关键词时，考虑 Cloze
- 高优先级内容时，考虑 Reverse

## Bad 反面案例

把80字解释硬做成QA，让用户背全文

**问题:** 记忆负担过大，违背题型守恒

## Good 正面案例

80字解释→IR卡；其中3个关键术语再各做1张CL卡

**优点:** 最小记忆负担，分层记忆

## 快速映射表

| 场景示例 | 推荐题型 | 模板代码 |
|----------|----------|----------|
| 长段材料、眼熟即可 | IR | `{"type":"IRead","back":"{{Question}}<hr>{{Answer}}"}` |
| 名词解释、事实问答 | QA | `{"type":"Basic","front":"{{Q}}","back":"{{A}}"}` |
| 概念串、时间链、定义句 | CL | `{"type":"Cloze","text":"{{c1::A}}导致{{c2::B}}"}` |
| 外语单词、易混词 | RC | `{"type":"Reverse","front":"{{E}}","back":"{{C}}"}` |
| 集合/枚举≥5项 | CL-重叠 | `{"text":"{{c1::A}}→{{c2::B}}→{{c3::C}}..."}` |

## 实施要点

- 优先选择记忆负担最小的题型
- IRead 用于长文本（>30字）或只需眼熟的内容
- Basic 用于简短事实（≤15字）
- Cloze 用于包含多个关键词的句子
- Reverse 用于高价值、易混、语言对

## 与其他原则的关系

- **原子职责**: 同时检查"题型是否最小"
- **最小上下文**: IR卡允许30-100字，QA/CL仍≤25字
- **冗余可逆**: 仅对QA/CL执行，IR卡不做反向
