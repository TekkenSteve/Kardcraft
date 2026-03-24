---
name: principle-redundant-safe
description: 冗余可逆原则 - 同一高价值知识用正反面、多角度复现，增强记忆
keywords: [anki, principle, redundancy, reverse, high-priority, cognitive]
priority: 75
category: cognitive
applicable_subjects: [all]
applicable_contexts: [high_priority]
---

# 冗余可逆 Redundant but Safe

## 定义

同一高价值知识用正反面、多角度复现。

## Agent 规则

```python
if card.priority > 0.9:
    flip() + example()
```

## 使用时机

- 高优先级知识（priority > 0.9）
- 核心概念
- 易混淆的重要知识
- 语言学习（单词、短语）

## Bad 反面案例

只有英→中，没有中→英

**问题:** 单向记忆，无法主动输出

## Good 正面案例

双向卡片 + 例句卡

**优点:** 多角度强化，主动+被动记忆

## 实施要点

- 高价值知识多角度覆盖
- 正反向卡片都要有（Reverse 类型）
- 增加应用场景卡
- 添加例句、用法说明
- 不同角度提问同一知识点

## 与其他原则的关系

- **题型守恒**: 使用 Reverse 类型实现双向
- **干扰对冲**: 易混概念更需要冗余
