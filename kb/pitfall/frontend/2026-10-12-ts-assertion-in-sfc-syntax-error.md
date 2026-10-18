---
id: kb-20261012-950c
title: Vue SFC 中 TS 类型断言会报 `Unexpected identifier 'as'`
type: pitfall
domain:
- frontend
tags:
- vue-sfc
- typescript
- vite
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# Vue SFC 中 TS 类型断言会报 `Unexpected identifier 'as'`

## 背景 / 现象

浏览器控制台报 `SyntaxError: Unexpected identifier 'as'`，对应 Vue Router 的 `uncaught error during route navigation`，页面白屏。

## 根因

`.vue` 文件的 `<script setup>` 未声明 `lang="ts"` 时，Vite/Vue 编译器按普通 JavaScript 处理。模板或脚本里若写了 TypeScript 类型断言（如 `:default-checked-keys="[] as string[]"`），浏览器执行到 `as` 关键字即抛 SyntaxError。

## 解决方案

1. 优先去掉无意义的类型断言：`:default-checked-keys="[]"`。
2. 如确需 TS，给 script 标签加 `lang="ts"` 并确保项目配置支持（tsconfig、Vite plugin 等）。
3. 排查"Unexpected identifier"时，优先检查最近改动/当前路由对应的 `.vue` 文件是否混用了 TS 语法。

## 验证

（自本条方案段提取）去掉/改正断言后浏览器不再报 `Unexpected identifier`；排查时优先检查最近改动或当前路由对应的 `.vue` 文件是否混用了 TS 语法。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/构建工具与开发流程.md` :: 「Vue SFC 中 TS 类型断言会报 `Unexpected identifier 'as'`」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
