---
id: kb-20261012-0677
title: 初次登录 401 兜底路径静默无提示，且 `location.href` 会打断 toast
type: pitfall
domain:
- frontend
tags:
- interceptor
- toast
- location-href
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 初次登录 401 兜底路径静默无提示，且 `location.href` 会打断 toast

## 背景 / 现象

登录页使用错误账号密码（如 `BADUSER99`）登录，后端返回 `401 Unauthorized`（`AUTH_001` "用户名或密码错误"），但前端页面上看不到任何错误提示，用户无从得知是密码错还是网络断连；同时浏览器地址栏的 `redirect` 参数被反复追加，URL 无限膨胀（`/login?redirect=%2Flogin` → `/login?redirect=%2Flogin%3Fredirect%3D%252Flogin` → ……）。

## 根因

`request.js` 的 401 响应拦截器兜底路径只做了：取 `msg` → 若无 refreshToken 直接 `logoutAndRedirect()` → `Promise.reject(new Error(msg))`。**从未调用 `ElMessage`/`ElNotification` 展示 `msg`**。更深一层：即使之前手工加过 `ElMessage.error(msg)`，紧随其后的 `location.href = /login?redirect=...` 会同步触发 page unload，toast 节点随组件树被销毁，用户依然看到的是空白。而 `logoutAndRedirect()` 拼 redirect 参数用 `location.pathname + location.search`，本身在登录失败时已带了上一次的 `redirect`，再次 encodeURIComponent 折叠后产生指数级 URL 膨胀。

## 解决方案

1. 401 拦截器内新增 `isLoginFlow` 判定：`/^\/auth\/(login|refresh)/.test(url) || !getRefreshToken()`，命中时**显式 `ElMessage.error(msg)`** 展示后端返回的具体原因（如 `AUTH_001` "用户名或密码错误"），再 `logoutAndRedirect()`
2. `logoutAndRedirect()` 拼 redirect 仅取 `location.pathname`（**不再包含 `location.search`**），避免在 `/login?redirect=...` URL 上二次折叠追加：
   ```js
   location.href = `/login?redirect=${encodeURIComponent(location.pathname)}`
   ```
3. **凡涉及 `location.href` 跳转 + 同时需要 toast 的场景**，要么在跳转前给 toast 留出足够展示时长（`setTimeout` 延迟跳转，或让用户手动点击"知道了"），要么改走 SPA 内 `router.replace('/login')` 让组件树保持挂载。**这是 `location.href` 全局导航与 Element Plus toast 节点生命周期的天然冲突**，凡新增"失败后跳登录页并显示原因"的路径都应核查此项

## 验证

用 Trae 内嵌沙箱做测试时，`ElMessage` 挂载的 toast 节点确实会被 page unload 销毁，MutationObserver 也抓不到（节点在 DOM 卸载时被移除），因此 toast 是否真正展示**只能依赖真实浏览器的肉眼验证**；沙箱中能可靠的间接证据只有：① URL 变化轨迹（能证明拦截器走到了登出/重定向分支）、② 后端日志命中（证明请求到达并返回了正确错误码）、③ 代码逻辑闭环核查（isLoginFlow 分支 + ElMessage.error 调用）。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
