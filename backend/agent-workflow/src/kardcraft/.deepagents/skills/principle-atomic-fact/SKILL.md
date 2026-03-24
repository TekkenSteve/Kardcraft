---
name: principle-atomic-fact
description: 原子职责原则 - 一卡只测一个不可再拆的最小事实，答案不超过15字
keywords: [anki, principle, atomic, card-creation, core]
priority: 100
category: core
applicable_subjects: [all]
applicable_contexts: [all]
---

# 原子职责 Atomic Fact

## 定义

一卡只测一个不可再拆的最小事实。

## Agent 规则

```python
if len(answer.split('。')) > 1:
    split()
```

## 使用时机

- 创建任何 Anki 卡片时
- 检测到答案包含多个句子时
- 答案超过15字时（除非图卡）

## Bad 反面案例

**Q:** 衰老细胞特征？  
**A:** 6行大段文字

**问题:** 包含多个独立事实，无法原子化记忆

## Good 正面案例

**Q:** 衰老细胞体积变化？  
**A:** 变小

**优点:** 单一事实，清晰明确

## 实施要点

- 一张卡片 = 一个原子知识点
- 答案不超过15字（除非图卡）
- 避免复合问题
- 如果答案包含多个句子，拆分成多张卡片

## 与其他原则的关系

- **题型守恒**: 同时检查"题型是否最小"
- **最小上下文**: 题干也要保持最小
- **枚举拆片**: 列表类内容的特殊处理方式
