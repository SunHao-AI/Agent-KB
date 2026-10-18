---
id: kb-20261012-2c7d
title: 对话框内 el-table 列宽溢出
type: pitfall
domain:
- frontend
tags:
- el-table
- dialog
- layout
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# 对话框内 el-table 列宽溢出

## 背景 / 现象

当 el-table 各列固定宽度（width/min-width）之和超过所在 el-dialog 的内容区宽度（对话框宽度减去左右内边距约 32px）时，表体会出现横向滚动、右侧列被部分遮挡，且表头保持表格总宽显得"超出"容器。

## 根因

这不是表头本身的问题，而是表格总宽超出容器宽度。

## 解决方案

加宽对话框（如 840px→960px）或减小列宽，确保列宽合计 < 内容区宽度。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「对话框内 el-table 列宽溢出」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

`ModelUpload.vue` 上传弹窗、`models/index.vue` 引用详情弹窗。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
