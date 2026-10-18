---
id: kb-20261012-0e03
title: 自定义网格/表格标签列宽需统一
type: pitfall
domain:
- frontend
tags:
- grid
- label
- style
scope: universal
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# 自定义网格/表格标签列宽需统一

## 背景 / 现象

自定义网格（如 param-grid）的标签列宽过窄，导致文字截断、各标签视觉宽度不一致。

## 根因

标签列固定宽度未容纳最长标签文本。

## 解决方案

统一加宽标签列（如 76px→128px），并保证所有标签宽度一致。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「自定义网格/表格标签列宽需统一」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「自定义网格/表格标签列宽需统一」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
