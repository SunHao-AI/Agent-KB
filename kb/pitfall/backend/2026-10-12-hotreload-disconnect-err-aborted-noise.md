---
id: kb-20261012-7ff6
title: 改后端文件后浏览器出现 `net::ERR_ABORTED`：热重载断连，不是后端故障
type: pitfall
domain:
- backend
tags:
- uvicorn-reload
- err-aborted
- dev-noise
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-10'
updated: '2026-10-18'
review_by: '2027-04-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# 改后端文件后浏览器出现 `net::ERR_ABORTED`：热重载断连，不是后端故障

## 背景 / 现象

**现象**：改完 backend 文件，浏览器 console 报 `net::ERR_ABORTED http://127.0.0.1:5173/v1/exports?...`（走 `axios → dispatchXhrRequest`），看起来像接口挂了。

## 根因

uvicorn `--reload` 的 WatchFiles 检测到后端文件变更即重启 worker, 重启瞬间掐断 Vite dev proxy 的全部在途上游连接; 浏览器侧把被代理层断掉的请求记为客户端中止 `ERR_ABORTED`, 而后端根本没机会产生业务错误码, 故该报错只是 dev 热重载时序噪声.

## 解决方案

（自本条边界段提取）

- 看到 dev 环境 `ERR_ABORTED` 先查两件事：后端日志该 URL 的状态码 + 是否有 `Reloading...`。两者同时满足就是热重载噪声，不用改代码。
- 不要在验收期间随手编辑 backend 文件；要做埋点就一次性改完再测，否则每写一次盘都会制造一批假失败。
- 想彻底消噪：把验收请求挪到不活跃改码的时段，或临时把 backend 起成无 reload（`uvicorn backend.main:app`）。

## 验证

原文「判定」段(实测): `docker logs` 同窗口该 URL 全是 200 OK, 且伴随 `WatchFiles detected changes ... Reloading...`; 与真故障(其它接口一起阻塞、探测 /health 十几秒无响应)可对照区分。

## 适用边界与反例

**判定**：`docker logs flysee-video-setting-backend` 里同窗口该 URL **全是 200 OK**，且能看到 `WatchFiles detected changes in 'backend/...'. Reloading...` + `Started server process [pid]`。说明是 uvicorn `--reload` 重启 worker 的**瞬间**，Vite dev proxy 的在途请求被上游断开，浏览器侧记为客户端中止（`ERR_ABORTED`），**没有任何业务错误码**。

**与真故障的区别**：真的把事件循环卡住时（见「创建导出 `net::ERR_ABORTED`：`async def` 端点内跑同步打包」条目），`ERR_ABORTED` 会伴随**其它接口一起阻塞**（探测 `/health` 十几秒无响应）；热重载只是毫秒级断连，F5 后即恢复。

**要点**：

- 看到 dev 环境 `ERR_ABORTED` 先查两件事：后端日志该 URL 的状态码 + 是否有 `Reloading...`。两者同时满足就是热重载噪声，不用改代码。
- 不要在验收期间随手编辑 backend 文件；要做埋点就一次性改完再测，否则每写一次盘都会制造一批假失败。
- 想彻底消噪：dev 用 `--reload` 但把验收请求挪到不活跃改码的时段，或临时把 backend 起成无 reload（`uvicorn backend.main:app`）。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
