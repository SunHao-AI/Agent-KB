---
id: kb-20261013-0f09
title: setInterval 异步回调用 `continue` 跳过本轮：IDE 诊断与 vitest 全绿，只有 build:prod 才炸
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/乐观态反馈与慢接口.md
---

# setInterval 异步回调用 `continue` 跳过本轮：IDE 诊断与 vitest 全绿，只有 build:prod 才炸

## 背景 / 现象

改轮询守卫时把跳过条件写成 `continue`（它是 `setInterval(async () => {...})` 回调，**不在循环体内**）。`GetDiagnostics` 零错误、`npm test` 195 全过，直到 `docker compose build` 才报 `[vue/compiler-sfc] Unsyntactic continue`，白烧一轮镜像构建。

## 根因

IDE 语言服务对 `.vue` 内 `<script setup>` 的语法检查覆盖不全（模板编译期才暴露），vitest 走 esbuild transform 对该错误也宽容放行；只有 rollup/vue-compiler 的正式构建做完整 AST 校验。

## 解决方案

回调内跳过本轮用 `return`；且"跳过时不触发超时告警、继续时触发"的语义用**单个 if 判定块**表达（`if (settled && dispatched) {...; return}` 落到尾部统一查 `ticks`），避免多个提前 return 吞掉尾部的超时兜底逻辑。

## 验证

改轮询守卫时把跳过条件写成 `continue`（它是 `setInterval(async () => {...})` 回调，不在循环体内）。`GetDiagnostics` 零错误、`npm test` 195 全过，直到 `docker compose build` 才报 `[vue/compiler-sfc] Unsyntactic continue`，白烧一轮镜像构建。

## 适用边界

- **改完 `.vue` 的验证链必须含 `npm run build:prod`**（或 docker build），IDE 诊断 + 单测不能替代它——这是本轮唯一能抓住该错误的环节，放最后白烧构建。

- 定时器回调里不存在 `continue/break`；改写"跳过本轮"时优先重构成**正向条件块**而非多个提前 `return`，防止提前返回吞掉回调尾部的超时/清理兜底。

## 参考

- 源记录: `docs/known-pitfalls/frontend/乐观态反馈与慢接口.md` 「setInterval 异步回调用 `continue` 跳过本轮：IDE 诊断与 vitest 全绿，只有 build:prod 才炸」
