---
id: kb-20261013-df33
title: ElNotification 的 onClose 绑在 onBeforeLeave（异步）：程序性 close 重开时同步标志位竞态清错状态
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
review_by: '2027-04-11'
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/SSE实时化与重连.md
---

# ElNotification 的 onClose 绑在 onBeforeLeave（异步）：程序性 close 重开时同步标志位竞态清错状态

## 背景 / 现象

- 任务启动失败聚合通知：第一条失败弹通知，第二条失败时代码先 `failNotif.close()` 再重开新通知——期望累计计数保留并递增，实际第二、三条只报"任务启动失败"（计数丢了）。

## 根因

- 第一版用同步布尔 `failNotifClosing` 包住 `close()` 调用来区分"程序性关闭"与"用户手动关闭"——但 Element Plus notification 源码（`notification2.mjs`）把 `onClose` 绑在 **`onBeforeLeave`**，即 leave 过渡动画前才触发，**异步**。`close()` 返回后标志位已复位，稍后 `onClose` 才执行 → 把"程序性重开"误判成"用户关闭"，清单被清空。

## 解决方案

```js

let failNotifToken = 0

const pushLaunchFailure = (taskId, reason) => {

  failNotifToken += 1

  const myToken = failNotifToken

  if (failNotif) { failNotif.close(); failNotif = null }

  failNotif = ElNotification({

    ...,

    onClose: () => {

      // 只有"当前这条"被关闭（= 用户关掉的）才清累计清单；

      // 被后续通知程序性顶掉的旧条 token 已过期，不动清单

      if (failNotifToken === myToken) { failNotifList = []; failNotif = null }

    },

  })

}

```

## 验证

- 判据：**对"关闭时才触发"的组件回调（onClose/onTransitionEnd 等），永远假设它是异步的**——不要指望"同步 set 标志 → close() → 同步复位"能框住回调执行窗口。区分调用来源用单调递增 token/序号比对，不用布尔标志位。

- 同类陷阱面：Element Plus Dialog/Drawer 的 `@close` 也挂在 leave 过渡上，写"关闭后清理/区分来源"逻辑时同样适用。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/SSE实时化与重连.md` 「ElNotification 的 onClose 绑在 onBeforeLeave（异步）：程序性 close 重开时同步标志位竞态清错状态」
