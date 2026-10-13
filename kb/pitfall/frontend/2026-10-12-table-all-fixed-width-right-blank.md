---
id: kb-20261012-7629
title: el-table 全部列固定 width 时右侧出现空白
type: pitfall
domain:
- frontend
tags:
- el-table
- min-width
- layout
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# el-table 全部列固定 width 时右侧出现空白

## 背景 / 现象

el-table 所有列均用固定 `width`（如 版本列表：160/140/120/90/90/100/170/220=1090px），容器比列宽合计更宽时，表格右侧出现一段空白（视觉上类似 th 设置了 right-margin），表体宽度停在列宽合计、不随容器拉伸。

## 根因

Element Plus 的 `table-layout.mjs updateColumnsWidth` 中，只有存在"无固定 width 的列"（flex 列，即用 `min-width` 的列）且 `fit` 为 true 时，才会把剩余宽度分配给 flex 列使表格撑满容器；全部列都设了 `width` 时走 else 分支，表格宽 = 列宽合计，容器多出的宽度就成了右侧空白。

## 解决方案

把需要自适应填充的列（通常是末列，如"操作"）由 `width="220"` 改为 `min-width="220"`，使其成为 flex 列自动吸收剩余宽度；容器变窄时仍按最小宽度出横向滚动，行为与原来一致。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

`models/detail.vue` 版本列表"操作"列。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
