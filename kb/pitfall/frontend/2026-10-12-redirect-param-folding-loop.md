---
id: kb-20261012-ec89
title: 登录失败后 URL `?redirect=` 多折叠（URL bar 嵌套 3 层）
type: pitfall
domain:
- frontend
tags:
- redirect
- url
- login
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 登录失败后 URL `?redirect=` 多折叠（URL bar 嵌套 3 层）

## 背景 / 现象

在 `/index` 触发 401（如 TOTP 错、密码错、access 过期）跳回登录页，URL 反复嵌套：`/login?redirect=%2Flogin%3Fredirect%3D%252Flogin%252F2fa`。刷新/继续操作不会自然恢复。

## 根因

`permission.js` 三个折叠点：
1. `permission.js:72` `return /login?redirect=${encodeURIComponent(to.fullPath)}` —— `to.fullPath` 已含查询，直接编码追加，每次折叠添一层
2. `request.js` `logoutAndRedirect()` 用 `location.pathname`（已修）
3. `request.js` HTTP error 401 分支用 `location.pathname + location.search`（原样折叠）

每次 `401 任意 → push /login?redirect=当前路径+当前 query → 下一次 401 → 再把?redirect=?... 编码追加`，所以堆 N 层。

## 解决方案

`validate.js#normalizeRedirect` 统一展开折叠（只剥 `/login?redirect=` 路径），三处调用方式：
- `permission.js:81/93`：`return /login?redirect=${encodeURIComponent(normalizeRedirect(to.fullPath))}`
- `request.js` `logoutAndRedirect()` / HTTP 401 分支：`location.href = /login?redirect=${encodeURIComponent(normalizeRedirect(current))}`
- 再加防御：循环解码 ≤8 次防死循环

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「登录失败后 URL `?redirect=` 多折叠（URL bar 嵌套 3 层）」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

不是 URL Display 问题——折叠 URL 是数据，新 URL 上 `normalizeRedirect` 后再编码就到 1 层。

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
