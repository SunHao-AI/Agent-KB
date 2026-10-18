---
id: kb-20261013-a568
title: '`ElMessage.error(err)` 直传 Error 对象 → `setAttribute: Cannot convert object
  to primitive value`'
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-13'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/请求错误提示与BizError.md
---

# `ElMessage.error(err)` 直传 Error 对象 → `setAttribute: Cannot convert object to primitive value`

## 背景 / 现象

控制台成对报错（栈顶是 Vue Router 内部的 `triggerError`，非业务代码）：

```

net::ERR_ABORTED  http://localhost:15173/v1/getInfo

TypeError: Failed to execute 'setAttribute' on 'Element': Cannot convert object to primitive value

```

同一签名此前在「expired 态 `/license` 白屏」里出现过一次（见 `授权状态与全局横幅.md`），当时只修了 `/license` 进 whiteList，**`ElMessage.error(err)` 这个原始触发点一直没动**，于是换个诱因（后端重启导致 getInfo 超时）又复现。

## 根因

两段独立成因叠在一起：

1. **`ERR_ABORTED` 是前端自己掐的，不是后端故障**。axios 实例 `timeout: 10000`，超时后内部调 `xhr.abort()`，浏览器记 `ERR_ABORTED`；nginx 侧对应 **499**（`client closed request`）而非 5xx，后端日志里查不到这条请求的完成记录。本次 nginx 日志与 `@vite/client` 请求相隔整 10s，即超时值。排查时先看 nginx 状态码：499 = 客户端断开，别去翻后端。

2. **`setAttribute` 报错来自把 reject 出来的对象直接喂给 ElMessage**。`err` 是 AxiosError 对象；`request.js` 的 error 分支对 "Request aborted" 没有任何特判，走完通用分支后仍 `Promise.reject(error)` 原样上抛；守卫 `ElMessage.error(err)` 收到非原始值，Vue 的 `patchProp` 只在值为字符串时才 `String(n)`，对象直接下传 DOM → 抛 `Cannot convert object to primitive value`；异常从守卫冒泡到 vue-router 的 `triggerError`，被 `console.error` 打出来，看起来像「路由报错」，实际根子在消息提示。

## 解决方案

守卫 catch 里必须把错误收敛成字符串再提示：

```js

} catch (err) {

  await useUserStore().logOut()

  // err 常为 AxiosError 对象，直传 ElMessage 会触发

  // setAttribute: Cannot convert object to primitive value，必须先收敛成字符串

  ElMessage.error(err?.message || '获取用户信息失败，请重新登录')

  return { path: '/' }

}

```

## 验证

`ElMessage` / `ElNotification` / `ElMessageBox` 的 message、title 一类字段只接受 string / VNode，**禁止把 catch 到的 `err` 原样传入**，一律 `err?.message || '兜底文案'`。全项目 44 处 `ElMessage.error(...)` 调用，历史上仅此一处传对象——新增代码按此自查即可。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/请求错误提示与BizError.md` 「`ElMessage.error(err)` 直传 Error 对象 → `setAttribute: Cannot convert object to primitive value`」
