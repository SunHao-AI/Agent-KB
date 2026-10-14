---
id: kb-20261013-91a7
title: keep-alive 多页共存：页面卸载裸 `close()` 共享 SSE 单例 → 误杀其它页订阅
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-13'
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/SSE实时化与重连.md
---

# keep-alive 多页共存：页面卸载裸 `close()` 共享 SSE 单例 → 误杀其它页订阅

## 背景 / 现象

- 任务列表切到任务详情后，详情页对外部状态变化（API 停/启任务）毫无反应，只能手动刷新；

- 从 tagsView 打开多个任务详情（keep-alive 缓存多实例）时任一实例离开都会"传染"其它实例。

## 根因

- 任务相关页全在 keep-alive 缓存名单（`AppMain.vue` `<keep-alive :include="cachedViews">`，路由均无 noCache）；路由切换顺序是**先挂新页（mounted/activated）、leave 动画后才卸旧页（deactivated/unmounted）**。

- `sse.js` 是模块级单例（一条 EventSource + handlers 集合）。旧页面 `onUnmounted` 里裸调 `sse.close()`：新页 `connect()` 刚命中幂等复用，旧页 `close()` 却把**共享连接整个关掉并 `handlers.clear()`**——新页刚注册的订阅被一并清空。

- detail.vue 缓存多实例同理：后离开者的 `close()` 杀掉先离开/仍在场的全部订阅。

## 解决方案

1. `sse.js` 增加 `acquire()/release()`：连接生命周期 = 最后一个活跃页 release 之时；计数归零**宽限 2s**（`GRACE_CLOSE_MS`）才真 close——覆盖 out-in 过渡"先卸旧后挂新"的间隙，窗口内重新 acquire 直接复用现有连接（免多余 ticket/事件空窗）；`close()` 保留显式全关语义并同步 `refCount = 0`。

2. `use-task-events.js` 的 `useTaskSSE(onEvent, {onReconnect})`：mounted/activated → acquire、deactivated/unmounted → release；handler 只在活跃期挂载（缓存页后台零空转）；`acquire()` resolve 时若已 deactivated 立刻让位不订阅（快速切页竞态）。

3. 页面侧禁止再裸用 `connect()/close()`；rejoin/重连经 `onReconnect` 补偿刷新（断连期间事件不重放）。

```js

// 页面正确姿势

useTaskSSE((evt) => { ... }, { onReconnect: () => refreshSilently() })

```

## 验证

- `sse.spec.js` +5 引用计数用例：首份才 connect、跨页 release→acquire 净额≥0 不 close、宽限期复用免 ticket、`close()` 清计数、多余 release 不变负；

- 浏览器实测：列表停留时 API 停任务 ~2s 行内自动变「已停止」；详情停留时 API 启动自动流转；详情→列表（缓存实例）rejoin 补偿刷新；来回切页后连接仍存活持续收事件。

- 通用判据：**凡是"模块级单例长连接 + keep-alive 页面"组合，页面卸载钩子里绝不允许直接关共享资源**，必须引用计数或提升到路由层之上管理。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/SSE实时化与重连.md` 「keep-alive 多页共存：页面卸载裸 `close()` 共享 SSE 单例 → 误杀其它页订阅」
