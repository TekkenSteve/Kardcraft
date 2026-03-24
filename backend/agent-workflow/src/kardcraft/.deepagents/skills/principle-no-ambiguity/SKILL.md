---
name: principle-no-ambiguity
description: 无二义性原则 - 题干与答案指向唯一，易混概念同屏对比，避免歧义
keywords: [anki, principle, clarity, disambiguation, core]
priority: 95
category: core
applicable_subjects: [all]
applicable_contexts: [all]
---

# 无二义性 No Ambiguity

## 定义

题干与答案指向唯一；易混概念同屏对比。

## Agent 规则

```python
if acronym:
    add_domain_prefix()
```

## 使用时机

- 遇到缩写词时
- 遇到多义词时
- 遇到易混概念时

## Bad 反面案例

**Q:** GRE代表？  
**A:** 糖皮质激素反应元件

**问题:** GRE 可能指考试、基因元件等多个含义

## Good 正面案例

**Q:** bioch:GRE？  
**A:** 糖皮质激素反应元件

**优点:** 加领域前缀，消除歧义

## 实施要点

- 缩写词必须加领域前缀（如 bioch:, cs:, math:）
- 避免模糊词汇
- 提供必要上下文
- 易混概念成对出现

## 与其他原则的关系

- **干扰对冲**: 易混概念的处理方式
- **最小上下文**: 在保持最小的同时确保无歧义
