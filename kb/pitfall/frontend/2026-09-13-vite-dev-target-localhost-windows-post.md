---
id: kb-20261013-80d0
title: vite dev 代理 target 用 `localhost` 导致 Windows 下登录等 POST 请求挂起超时
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-13'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/开发代理与启动.md
---

# vite dev 代理 target 用 `localhost` 导致 Windows 下登录等 POST 请求挂起超时

## 背景 / 现象

本地 `npm run dev` 起前端后，登录页输入正确密码（`.env` 的 `DEV_DEFAULT_LOGIN_PASSWORD` 预填值、且已核实与 DB 中 bcrypt hash 匹配）点击登录**一直转圈失败**。迷惑点：

- 静态页面、GET 请求全部正常——只有登录（POST `/v1/login`）不通

- 直接对后端 `POST http://127.0.0.1:17998/v1/login` **秒回 200 + token**

- 经 vite 代理 `POST http://127.0.0.1:15199/v1/login` **挂满 20s+ 超时**

## 根因

```js

const backendTarget = process.env.BACKEND_PROXY_TARGET || `http://localhost:${backendPort}`

```

Windows 上 Node 18+ 把 `localhost` **优先解析为 IPv6 `::1`**，而 uvicorn 后端只监听 IPv4。http-proxy 连 `::1:17998` 连不上又不至于立刻 ECONNREFUSED（防火墙丢包/等待），表现为长挂起。GET 静态资源不经过代理所以无感知，**只有走代理的 API 请求受害**——极易误判为"密码错了"或"后端坏了"。

## 解决方案

代理 target 一律写显式 IPv4：

```js

// 必须用 127.0.0.1 而非 localhost：Windows + Node18 把 localhost 优先解析为 IPv6 ::1，

// 而后端只监听 IPv4，代理 POST 会挂起直到超时（登录表现为"无法登录"，GET 静态页不受影响）

const backendTarget = process.env.BACKEND_PROXY_TARGET || `http://127.0.0.1:${backendPort}`

```

## 验证

「页面能开、API 全挂/部分挂」时，先做**二分**：同一请求分别打「vite 端口」与「后端端口直连」。直连秒回而经代理挂起 → 问题必在代理层 target 解析，与业务代码无关。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/开发代理与启动.md` 「vite dev 代理 target 用 `localhost` 导致 Windows 下登录等 POST 请求挂起超时」
