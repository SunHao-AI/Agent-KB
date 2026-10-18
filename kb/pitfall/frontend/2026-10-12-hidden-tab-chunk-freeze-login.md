---
id: kb-20261012-1f1e
title: 后台标签页懒加载 chunk 冻结致登录后按钮无限"登录中..."（2026-10-11，web）
type: pitfall
domain:
- frontend
tags:
- lazy-load
- browser
- login
- watchdog
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-10-11'
updated: '2026-10-18'
review_by: '2027-04-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/登录鉴权与keep-alive.md
---

# 后台标签页懒加载 chunk 冻结致登录后按钮无限"登录中..."（2026-10-11，web）

## 背景 / 现象

登录页点"登录"后按钮永久停在"登 录 中..."。nginx/后端日志显示 `POST /v1/login 200` → `GET /v1/getInfo 200` 完整成功，之后**再无任何请求**；同浏览器把同一标签页切到前台 F5 重登则 1 秒进 dashboard。

## 根因

getInfo 之后前端路由守卫还要 `router.push` → 懒加载目标路由 chunk。浏览器对**隐藏/节能标签页**冻结定时器与 `requestIdleCallback`（Vite modulepreload 依赖它），chunk 请求根本不发出，`router.push` 的 Promise 永不 settle——`.then` 走不完、`.catch` 不触发，`loading` 只有失败分支复位就无限挂起。自动化测试（UIA `Ctrl+T` 开的后台页）与开了内存节省的普通用户都会踩中。

## 解决方案

（web `login.vue`，commit `1d4d2298`）：登录成功后起 15s 看门狗 `setTimeout`，超时 `loading=false` + `ElMessage.warning('页面资源加载超时...')`；`router.push` 正常返回则 `finally` 清定时器。配套用 `loggedIn` 标志把两个失败域拆开：登录接口失败才清密码，导航失败（token 已有效）绝不清密码/登出。回归测试 `views/__tests__/login-nav-watchdog.spec.js` 三例：push 永不 settle→超时恢复且不清密码 / 正常完成不弹 / 登录失败清密码。

## 验证

（Vitest 组件测登录页）：
- `vi.mock` 工厂引用的变量必须 `vi.hoisted` 创建（工厂被提升到 import 之前求值）；
- `login.vue` 顶部 `watch(route, ...)` 要求 `useRoute()` 返回 **reactive** 对象，mock 返回普通对象会被 Vue 判为无效 watch source，immediate 回调收到 `undefined` 直接炸 `newRoute.query`；
- mock `ElMessage.warning` 别整包替换 `element-plus`（会破坏 `plugins: [ElementPlus]`），用 `vi.spyOn(ElMessage, 'warning')`。

凡"接口全 200 但 UI 卡住"，先对比 nginx access.log 里请求链断在哪一环，再看该标签页是否后台——断在懒加载 chunk（请求列表里没有对应 static/js 请求）即本条。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md`（未匹配到源段））。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md`
