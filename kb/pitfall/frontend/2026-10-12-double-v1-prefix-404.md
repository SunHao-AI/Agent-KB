---
id: kb-20261012-115a
title: '`request({ url: `${BASE}/xxx` })` 双写 `/v1` 前缀 → 后端 `/v1/v1/xxx` 404（flysee_video_web
  SSE）'
type: pitfall
domain:
- frontend
tags:
- axios
- base-url
- sse
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-18'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# `request({ url: `${BASE}/xxx` })` 双写 `/v1` 前缀 → 后端 `/v1/v1/xxx` 404（flysee_video_web SSE）

## 背景 / 现象

> 面向：`flysee_video_web/frontend` 凡用 `@/utils/request` 发请求、又手动在 url 里拼 `VITE_APP_BASE_API` 的地方。

后端日志 `POST /v1/v1/sse/ticket status=404`（`/v1` 重复）。其它走 `request` 的接口都正常，唯独 SSE 取票 404，前端 SSE 永远连不上、退化成轮询。

## 根因

`@/utils/request` 的 axios 实例 `baseURL = import.meta.env.VITE_APP_BASE_API || '/v1'`；`sse.js` 里 `_issueTicket` 又写了 `request({ url: `${BASE}/sse/ticket` })`（`BASE` 同样是 `VITE_APP_BASE_API`=`/v1`）。axios 拼成 `/v1` + `/v1/sse/ticket` = `/v1/v1/sse/ticket`。`src/api/*.js` 里所有 url 都是**不带 `/v1` 的相对路径**（`/system/license` 等），因为 baseURL 已带；只有 `sse.js` 例外，把 EventSource 需要的"绝对前缀"逻辑误用到了 `request` 上。

## 解决方案

`request` 调用一律传**不带 `/v1` 的相对 url**（`/sse/ticket`）；`BASE` 只留给 `new EventSource(`${BASE}/sse/stream?...`)`（浏览器原生 API 无 baseURL，才需要自己拼全路径）。同步改 `sse.spec.js` 断言为 `{ url: '/sse/ticket', method: 'post' }`。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

- **判断依据是"走不走 axios `request`"**：走 `request`/`axios` → url 相对（baseURL 已含 `/v1`）；走 `EventSource`/`fetch`/`<a href>`/`<img src>` 等原生 API → 自己拼 `VITE_APP_BASE_API` 全路径。同一模块里两种混用时（如 `sse.js` 既有 `request` 又有 `EventSource`）最易踩，`BASE` 只能加在原生 API 那一侧。
- 单测 `expect(request).toHaveBeenCalledWith({ url: ... })` 的 url 必须是相对路径，可作为回归哨兵。
- 前端是生产构建（dist 冻结镜像内），改 `sse.js` 后必须 `docker compose build frontend && up -d frontend` 才生效，后端日志才能验证。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
