---
id: kb-20261013-faba
title: ticket 换取 401（令牌过期）被当可重试错误 → 每 30s 一次 401 死循环 + toast 风暴
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-12'
updated: '2026-10-13'
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/SSE实时化与重连.md
---

# ticket 换取 401（令牌过期）被当可重试错误 → 每 30s 一次 401 死循环 + toast 风暴

## 背景 / 现象

浏览器测试与后端日志交叉实锤：某 keep-alive 任务页的 access token 过期后，后端每 ~31s 收到一次 `POST /v1/sse/ticket` **恒 401**，无限持续；页面"实时/离线"指示点永远停在"重连中"。

## 根因

- `scheduleReconnect` 对所有 `connect()` 失败一律再退避重连（attempts 夹 6 → backoff 封顶 30s），**不区分错误可恢复性**。

- 触发链：stream 瞬断（本仓 dev 常态：uvicorn reload 掐断在途 SSE）→ 重连需重新换 ticket → access token 已过期 → ticket 401 → `connect()` reject → `.catch` 再 `scheduleReconnect()` → **永久循环**。

- 401 对"同一过期令牌"是**不可恢复**的——重试永远 401。指数 backoff 只解决"瞬时故障的恢复速度"，不解决"终态错误的及时放弃"。

- 次生放大：ticket 请求未标 `silent`，每次 401 经全局响应拦截器 `ElMessage` 弹"登录状态已失效"红条 → 每 30s 一条 toast 风暴。

## 解决方案

1. `_isAuthExpiry(err)`（`err?.response?.status === 401`）判定终态：`scheduleReconnect` 的 catch 里命中即 `_setStatus('disconnected')` 并 return，**不再续定时器**（状态点如实转"离线"，用户重新登录后下一次 acquire 自然恢复）；

2. `_issueTicket` 的 request 加 `silent: true`：SSE 通道的失败由 SSE 自己消化，不弹全局 toast（登录引导已由业务请求/路由守卫负责，SSE 重复弹只会叠加噪音）。

## 验证

- `sse.spec.js` +3 护栏：重连遇 401 → 状态 `disconnected` 且再推 10 分钟 0 次 ticket/0 个新连接；首次 connect 即 401 不启动退避定时器。全量前端 **192 passed**。顺带修了测试基建隐患：`beforeEach` 用 `mockClear`（不恢复实现）会让上个 case 的 `mockImplementation` 泄漏到后续 case，改 `mockReset`。

- 行为级复验：部署新 bundle 后，原本每 31s 一次的 ticket 401 在 2 分钟窗口内降为 **0**。

- 通用判据：**任何自动重试机制必须显式分类"可恢复 vs 终态"**。凭据类错误（401/403）、权限类（403 资源级）、参数校验类（4xx）都是终态——对它们重试是纯放大；只有网络/5xx/超时才进退避循环。终态的正确处理是"停止 + 把状态如实告知 UI"，而不是"沉默地永远重试"。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/SSE实时化与重连.md` 「ticket 换取 401（令牌过期）被当可重试错误 → 每 30s 一次 401 死循环 + toast 风暴」
