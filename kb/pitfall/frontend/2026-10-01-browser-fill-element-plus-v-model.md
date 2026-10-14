---
id: kb-20261013-0924
title: browser_fill 对 Element Plus 表单输入框不触发 v-model：点提交永远报「请输入您的账号」，误判登录接口挂了
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/走查与自动化验证陷阱.md
---

# browser_fill 对 Element Plus 表单输入框不触发 v-model：点提交永远报「请输入您的账号」，误判登录接口挂了

## 背景 / 现象

会话过期被重定向到 /login（顺带实证 redirect 参数正常）。用 `browser_fill` 填账号密码点登录，页面**不跳转、无任何请求发出**，snapshot 出现表单校验文案「请输入您的账号」——像登录接口挂了，其实是值根本没进 Vue 状态。

## 根因

`browser_fill` 走 CDP 直接设 DOM `input.value`，**不派发 `input` 事件**（或派发的事件 Element Plus 的 `v-model` 监听不到），`loginForm.username/password` 始终为空串，前端表单校验直接拦下，请求根本没发。与「CDP fill 旁路 maxlength」同族：CDP 注入绕过的不止属性约束，还有框架响应式。

## 解决方案

- 可行写法：`Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(inp, val)` 用**原生 setter** 赋值（绕开 Vue 对实例属性的劫持）+ `dispatchEvent(new Event('input', { bubbles: true }))`，Vue 即感知。

- 判据：fill 后点提交若「无网络请求 + 出现 el-form-item__error」，先怀疑**值没进响应式**，别去查后端。快速鉴别：fill 后立刻 evaluate 读 `input.value` 与页面校验态——DOM 有值但校验报空 = 响应式没收到。

- 附：admin 密码别猜（`Admin@123`/`Admin@2026` 都错到「用户名或密码错误」浪费两轮）。dev 环境容器内 `settings.DEV_DEFAULT_LOGIN_PASSWORD` 即预填密码唯一事实源，`docker exec <backend> python -c "from backend.core.config import settings; print(settings.DEV_DEFAULT_LOGIN_PASSWORD)"` 一步拿到。

## 验证

实证：用 `browser_fill` 填账号密码点登录，页面不跳转、无任何请求发出，snapshot 出现表单校验文案「请输入您的账号」——值根本没进 Vue 状态。dev 环境容器内 `settings.DEV_DEFAULT_LOGIN_PASSWORD` 即预填密码唯一事实源（`docker exec <backend> python -c "from backend.core.config import settings; ..."` 查）。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/走查与自动化验证陷阱.md` 「browser_fill 对 Element Plus 表单输入框不触发 v-model：点提交永远报「请输入您的账号」，误判登录接口挂了」
