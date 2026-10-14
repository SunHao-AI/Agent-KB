---
id: kb-20261013-193b
title: fail-open 不等于"留在关键路径上"：遥测同步转发 566ms 白占浏览器连接位
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-03'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/授权三态与离线容器.md
---

# fail-open 不等于"留在关键路径上"：遥测同步转发 566ms 白占浏览器连接位

## 背景 / 现象

遥测转发同步等待网络，middleware `duration` 埋点扫到该请求耗时 566ms，白占浏览器同域连接位（非用户投诉，靠埋点巡检浮出水面）。

## 根因

`backend/api/v1/telemetry.py` 端点内 `await run_in_threadpool(client_obj.post_raw, ...)` 同步等 setting 签名转发往返（dev 跨容器+远端慢时整段网络时延计入响应）。"已经线程池化、已经 fail-open"掩盖了它仍**同步等待网络**的事实——线程池解决的是事件循环冻结，不解决响应关键路径。

## 解决方案

转发挪 `BackgroundTasks.add_task`（Starlette 对同步背景函数自动走线程池，在**响应发出之后**执行），handler 只剩毫秒级 DB 读 + 入队。实测 566ms → **7.8~12.6ms**；`tests/test_telemetry_relay.py` 9 例全过（TestClient 会同步等 background tasks，出站签名/字节透传断言原样兼容）。

## 验证

实测 566ms → **7.8~12.6ms**；`tests/test_telemetry_relay.py` 9 例全过（TestClient 会同步等 background tasks，出站签名/字节透传断言原样兼容）。

## 适用边界

- **"不报错"与"不等它"是两回事**。fire-and-forget 语义的正确实现是"响应先回、副作用后做"（BackgroundTasks / 队列），而不是"同步等待但吞异常"。凡业务上不消费返回值的下游调用，一律挪出关键路径。
浏览器同域 6 连接是公共资源：任何后台性质的前端请求（遥测、心跳、预取）都不得长占连接位。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权三态与离线容器.md` 「fail-open 不等于"留在关键路径上"：遥测同步转发 566ms 白占浏览器连接位」
