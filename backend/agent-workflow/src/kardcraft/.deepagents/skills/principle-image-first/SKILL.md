---
name: principle-image-first
description: 图优先原则 - 能图不文，图即题干，优先使用视觉化表达
keywords: [anki, principle, visual, image, diagram, core]
priority: 80
category: core
applicable_subjects: [biology, chemistry, physics, anatomy, geography]
applicable_contexts: [visual_concepts]
---

# 图优先 Image First

## 定义

能图不文；图即题干。

## Agent 规则

```python
if concept.has_diagram:
    image_cloze()
```

## 使用时机

- 视觉概念（解剖、地理、化学结构等）
- 空间关系
- 流程图、示意图
- 生物、化学、物理等学科

## Bad 反面案例

用文字描述"线粒体嵴位置"

**问题:** 文字描述空间关系效率低

## Good 正面案例

放一张标注图，问红色箭头指什么？

**优点:** 直观、高效、准确

## 实施要点

- 优先使用图像卡片
- 图像标注清晰
- 避免纯文字描述视觉概念
- 使用图像填空（Image Occlusion）
- 标注关键部位

## 与其他原则的关系

- **题型守恒**: 图像卡通常使用 Cloze 类型
- **原子职责**: 一张图只标注一个关键点
