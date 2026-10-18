---
id: kb-20261012-0fff
title: '`views/login.vue` 是被改造的单文件，不是 `views/login/index.vue`'
type: pitfall
domain:
- frontend
tags:
- vite-resolve
- file-naming
- router
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# `views/login.vue` 是被改造的单文件，不是 `views/login/index.vue`

## 背景 / 现象

按惯例"views 目录每模块下建 `index.vue`"新建了 `views/login/index.vue`，但 `router/index.js` 仍指向 `() => import('@/views/login')`，Vite 会解析到旧的单文件，新页面不生效；或反过来把 `views/login.vue` 删掉只留 `views/login/index.vue`，动态菜单未含 `/login` 时登录路由匹配失败进 404。

## 根因

`@/views/login` 通过 Vite import 解析规则优先尝试 `login.vue`（文件优先于目录的 `index.vue`）。改造时未核对路由入口指向。

## 解决方案

修改登录/2FA/强改密前先 `grep -r "@/views/login" src/router` 确认路由入口指向的是单文件还是目录 `index.vue`；本项目入口是 `views/login.vue`（单文件），2FA/强改密子页面为 `views/login/{2fa,forced-pwd}.vue`（子文件，不冲突）。**未来新增业务页若按 `views/<module>/index.vue` 惯例，务必同时把路由 entry 指向 `@/views/<module>`（目录）而不是 `@/views/<module>.vue`**。

## 验证

（自本条方案段提取）`grep -r "@/views/login" src/router` 确认路由入口实际指向的文件与改造目标一致；打开登录/2FA/强改密页渲染的是新代码（必要时看 Vite dev 网络面板命中哪个模块路径）。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
