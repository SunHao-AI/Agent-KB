---
id: kb-20261013-686b
title: 路由 spec 测 `meta.roles` 过滤的两个 vitest 拦路虎：动态 import 字面量被强制解析 + `@/layout` pwa
  虚拟模块加载失败
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
  ref: docs/known-pitfalls/frontend/测试环境与vitest.md
---

# 路由 spec 测 `meta.roles` 过滤的两个 vitest 拦路虎：动态 import 字面量被强制解析 + `@/layout` pwa 虚拟模块加载失败

## 背景 / 现象

给 `generateRoutes` 写 spec（断言 `/users` 路由按 `meta.roles` 对非 admin 置 hidden）时连环两处失败：

1. spec 只 import `permission.js` 与路由表，并未渲染任何组件，但 vitest 报**动态 import 的目标文件不存在**直接崩——被 `router/index.js` 里 `component: () => import('@/views/users/index.vue')` 的字面量在 **transform 阶段被强制解析**，即使该分支运行时永远不会执行；新页面路由先合入、`index.vue` 后合入的拆分方式会让既有 spec 当场 0 test。

2. 补了占位组件后又炸 `virtual:pwa-register/vue` 找不到——`@/layout` 组件链上引了 PWA 更新 composable，该虚拟模块只有 vite 插件在（dev/build）才存在，vitest 加载链路没有注册对应插件。

## 根因

1. vitest 4（vite 8 transform 管线）对 `import('...')` **字符串字面量**在编译期就做存在性解析（用于依赖图/HMR），不做"运行期才碰"的惰性豁免；`component` 字段写成箭头函数包裹只推迟**执行**，不推迟**解析**。

2. `virtual:` 前缀模块由插件 `resolveId` 供给，vitest 默认加载 `vite.config.js` 插件集时 PWA 插件处于 disabled 分支（`disable: mode !== 'production'` 之类），虚拟 id 无人认领。

## 解决方案

1. 路由任务与页面任务分 commit 时，**路由 commit 内同步落一个 4 行占位 `index.vue`**（`<template><div /></template>`），页面任务用 Write 整体覆盖——保证任一粒度上 spec 可跑、提交自洽（同「模块引用与提交完整性」主题的正向用法）。

2. spec 顶部显式切断 layout 依赖链：

```js

vi.mock('@/layout', () => ({ default: { template: '<router-view />' } }))

```

mock 只给 `default` 导出即可——`generateRoutes` 只把 `component` 当不透明引用做浅拷贝/过滤，从不实例化。

## 验证

- 前端全量 216 passed / 21 files（当时基线）零回归；

- 通用判据：**给 `router/index.js` 新增任何 `component: () => import('@/views/新目录/...')` 路由，同 commit 必须有该文件的占位或实体**，否则所有间接 import 路由表的 spec 集体崩；

- 凡被测模块经**引用链**（非直接调用）触到 vite 插件虚拟模块（`virtual:*`），spec 用 `vi.mock` 断链，别试图在 vitest 里补插件配置。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/测试环境与vitest.md` 「路由 spec 测 `meta.roles` 过滤的两个 vitest 拦路虎：动态 import 字面量被强制解析 + `@/layout` pwa 虚拟模块加载失败」
