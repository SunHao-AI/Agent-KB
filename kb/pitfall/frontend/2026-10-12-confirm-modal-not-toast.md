---
id: kb-20261012-b984
title: '"确认后才可提交"类交互需用弹窗阻断而非 toast'
type: pitfall
domain:
- frontend
tags:
- ux
- element-plus
- confirm
scope: universal
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表单交互与数据绑定.md
---

# "确认后才可提交"类交互需用弹窗阻断而非 toast

## 背景 / 现象

设计文档要求"framework 变更时弹出架构变更风险提示（确认后才可提交）"，实现仅 `ElMessage.warning` toast，用户可忽略直接提交。

## 根因

toast 只是通知不阻断流程，与"确认后才可提交"的交互语义不符。

## 解决方案

需要用户确认才能继续的交互用 `ElMessageBox.confirm`（await，取消则中止），toast 仅作操作反馈。注意 `ElMessageBox` 需从 element-plus 显式 import，且 catch 需区分用户取消（'cancel'/'close'，静默中止）与真实异常（提示错误）。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单交互与数据绑定.md`
