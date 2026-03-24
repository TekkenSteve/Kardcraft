---
name: principle-baseline-first
description: 基线先行原则 - 任何扩展卡片必须先保证基线概念已掌握，建立知识依赖
keywords: [anki, principle, dependency, prerequisite, core]
priority: 90
category: core
applicable_subjects: [all]
applicable_contexts: [all]
---

# 基线先行 Baseline First

## 定义

任何扩展卡片必须先保证基线概念已掌握。

## Agent 规则

```python
if card.baseline not in user.memory:
    queue(baseline)
```

## 使用时机

- 创建高级概念卡片时
- 检测到知识依赖时
- 用户学习新领域时

## Bad 反面案例

问"协方差矩阵"前未问"方差"

**问题:** 缺少前置知识，无法理解

## Good 正面案例

先问"方差"，再问"协方差"

**优点:** 知识递进，循序渐进

## 实施要点

- 建立知识依赖图
- 检查前置概念掌握度
- 自动插入基线卡片
- 标注卡片之间的依赖关系

## 与其他原则的关系

- **先整体后局部**: 概览卡是最基础的基线
- **难度递进**: 基线先行是难度递进的基础
