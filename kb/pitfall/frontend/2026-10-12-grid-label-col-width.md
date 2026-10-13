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
updated: '2026-10-12'
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

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
