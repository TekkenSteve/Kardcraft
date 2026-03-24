---
name: principle-top-down
description: 先整体后局部原则 - 先给树状概览，再发叶子卡片，建立知识结构
keywords: [anki, principle, structure, overview, core]
priority: 95
category: core
applicable_subjects: [all]
applicable_contexts: [all]
---

# 先整体后局部 Top-Down

## 定义

先给树状概览，再发叶子卡片。

## Agent 规则

```python
if topic.new:
    create([overview] + sub_cards)
```

## 使用时机

- 遇到新主题时
- 创建知识体系时
- 需要建立知识结构时

## Bad 反面案例

直接问 v=v₀+at 的符号含义

**问题:** 缺少整体认知，孤立的知识点

## Good 正面案例

先给"匀加速运动三公式"总览卡，再拆符号

**优点:** 先建立框架，再填充细节

## 实施要点

- 新主题必须先建立概览卡
- 概览卡包含知识结构图
- 细节卡片引用概览卡
- 使用树状或思维导图展示结构

## 与其他原则的关系

- **基线先行**: 概览卡本身就是基线
- **原子职责**: 概览卡可以例外，允许包含多个要点
