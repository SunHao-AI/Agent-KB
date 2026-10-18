---
id: kb-20261012-2007
title: Vite HMR 后浏览器 DOM 不更新（调试首页时反复踩到）
type: pitfall
domain:
- frontend
tags:
- vite
- hmr
- debugging
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# Vite HMR 后浏览器 DOM 不更新（调试首页时反复踩到）

## 背景 / 现象

改 `.vue` 后 `fetch('/src/views/index/index.vue')` 拿到的是一片最新编译过的 JS（包含新增的 `v-if/searchVisible/el-input`），但浏览器 DOM 毫无变化；多次强制 `location.reload/href/hash` 都没用。

## 根因

Windows + Docker bind mount 下 Vite 的 `usePolling` 周期长（`WATCHFILES_FORCE_POLLING`），且浏览器 SPA 已加载的 vue-router `<component :is>` 会 cache 当前动态组件实例。某些 SFC 改动被 vite 判为"全套热替换 undefined accept"，导致 layout 的全量加载分支被跳过。

## 解决方案

- **不要**只是因为浏览器 no update 就断言 vite 没编译成功——`fetch` 拿到的 JS 是真相，DOM 没动只是客户端 stale state。
- 调试用 `fetch('/xyz?<newQuery>')` 确认源码已经编译 OK；验证渲染对 DOM 的影响时，用截图截 header/console 三联；如果截图失败，用 `browser_evaluate` 读取 `.app-container.<scope>` DOM 内容比对。
- 实在不行让用户 **手动 Ctrl+Shift+R 硬刷新** 一次（清除 chrome 内存 module cache），后续 HMR 才正常。

## 验证

（自本条方案段提取）`fetch('/xyz?<newQuery>')` 拿到的 JS 已含新代码即为编译成功；渲染层用截图或 `browser_evaluate` 读 `.app-container.<scope>` DOM 内容比对；硬刷新一次后 HMR 恢复正常即确认是客户端 stale state。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/构建工具与开发流程.md` :: 「Vite HMR 后浏览器 DOM 不更新（调试首页时反复踩到）」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
