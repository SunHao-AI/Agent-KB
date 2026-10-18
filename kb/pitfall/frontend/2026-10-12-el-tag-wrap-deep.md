---
id: kb-20261012-4853
title: el-tag 状态标签图标与文字换行
type: pitfall
domain:
- frontend
tags:
- el-tag
- scoped
- deep
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# el-tag 状态标签图标与文字换行

## 背景 / 现象

上传模型状态标签（如"正在上传 (2/6)"）中 Loading 图标和文字被挤成两行。

## 根因

Element Plus el-tag 默认带 `max-width`，内容超过标签限制时换行；且首次修复时 scoped 样式未加 `:deep()`，导致 `.el-tag__content` 选择器无法命中子组件内部元素（Vue 3 scoped 只给子组件根元素加父组件 data-v 属性），修复未生效。

## 解决方案

对状态标签外层容器用 `:deep()` 穿透：`.upload-status :deep(.el-tag)` 设置 `max-width: none`，`.upload-status :deep(.el-tag__content)` 设置 `display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;`。**修改子组件内部元素样式时必须用 `:deep()`，否则 scoped 选择器失效**。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「el-tag 状态标签图标与文字换行」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「el-tag 状态标签图标与文字换行」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
