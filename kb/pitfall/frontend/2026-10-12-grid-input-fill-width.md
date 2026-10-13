---
id: kb-20261012-a466
title: 网格内容区应填充列宽
type: pitfall
domain:
- frontend
tags:
- grid
- flex
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

# 网格内容区应填充列宽

## 背景 / 现象

网格内输入控件固定宽度，与网格列宽不对齐，留下参差空白。

## 根因

输入控件未填充所在列剩余宽度。

## 解决方案

输入控件使用 `flex:1; min-width:0`，使各输入框与网格列宽对齐一致。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
