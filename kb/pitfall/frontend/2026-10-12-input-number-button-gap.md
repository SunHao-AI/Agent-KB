---
id: kb-20261012-543b
title: el-input-number 右侧增减按钮空隙
type: pitfall
domain:
- frontend
tags:
- el-input-number
- style
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

# el-input-number 右侧增减按钮空隙

## 背景 / 现象

Element Plus 的 el-input-number（controls-position="right"）右侧增减按钮与输入框之间出现空隙。

## 根因

默认增减按钮高为 `calc(50% - 1px)` 且分别距上下各 1px，合计小于输入框高度。

## 解决方案

覆盖样式使按钮 `top:0/bottom:0` 且 `height:50%`，填满输入框高度。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
