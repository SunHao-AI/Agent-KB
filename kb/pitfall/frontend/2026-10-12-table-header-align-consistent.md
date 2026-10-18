---
id: kb-20261012-2e7a
title: el-table 表头对齐不统一
type: pitfall
domain:
- frontend
tags:
- el-table
- align
- style
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

# el-table 表头对齐不统一

## 背景 / 现象

同一表格内各列表头对齐方式不一致，视觉错乱。

## 根因

混用 `align` 与 `header-align` 导致表头与单元格对齐控制混乱。

## 解决方案

同一表格内各列表头对齐方式保持一致（建议统一居中）。若需表头与单元格对齐不同，用 `header-align` 单独控制表头；否则统一用 `align` 同时控制表头与单元格。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「el-table 表头对齐不统一」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「el-table 表头对齐不统一」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
