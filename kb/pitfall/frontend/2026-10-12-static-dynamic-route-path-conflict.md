---
id: kb-20261012-0c2c
title: 动态路由（后端菜单）与静态路由同 path 冲突导致重复挂载
type: pitfall
domain:
- frontend
tags:
- router
- dynamic-route
- duplicate
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 动态路由（后端菜单）与静态路由同 path 冲突导致重复挂载

## 背景 / 现象

切换账号后侧边栏菜单出现重复的"算法管理/客户端管理/系统管理"等一级菜单，或直接访问 `/system/user` 时 vue-router 报 `route with name "User" already exists` 或首个意外命中。

## 根因

`constantRoutes` 中保留了早年硬编码的业务路由（`/algorithm-config`、`/client-config`、`/system-config`、`/models/:id` 等），后端 `/auth/menus` 动态下发的菜单树也含相同 path（M200/M300/M400 子节点）。两套路由同时 `router.addRoute`，vue-router 出现同名路由覆盖/path 冲突，侧边栏（一般走 `sidebarRouters`）重复渲染。

## 解决方案

Plan 1 M10 / Plan 2 已把 `router/index.js` 清理为只保留静态壳（/login、/login/2fa、/force-pwd、/profile、/lock、/401、/404、/、/redirect），所有业务路径改由 `permission.buildRoutes(menus)` 从后端 `/auth/menus` 动态生成。**新增业务视图不要再次在 `constantRoutes` 里硬编码**；如确需 hidden 详情页（`/models/:id`），须保证 name 与 path 都不与动态菜单冲突，或改为 `meta.activeMenu` 方案。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「动态路由（后端菜单）与静态路由同 path 冲突导致重复挂载」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「动态路由（后端菜单）与静态路由同 path 冲突导致重复挂载」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
