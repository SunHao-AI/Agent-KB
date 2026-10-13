---
id: kb-20261012-8797
title: 长文本展示
type: pitfall
domain:
- frontend
tags:
- tooltip
- ux
- display
scope: universal
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-13'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# 长文本展示

## 背景 / 现象

长文本（如 SHA256 哈希）被截断后无法查看全貌。

## 根因

表格/网格的列宽约束必然对 SHA256 这类定长无分隔哈希做截断渲染, 而截断后的前缀对人眼不可辨、又无任何交互可找回全值, 用户比对或复制时即失去信息. 故展示策略须"尽量多展示 + el-tooltip 兜底全值", 让截断只影响视觉布局不影响信息可达.

## 解决方案

长文本应尽量多展示，并用 el-tooltip 气泡展示完整信息。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
