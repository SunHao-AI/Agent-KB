---
id: kb-20261012-4e13
title: 菜单驱动的"全量清理"误删隐藏详情路由（/models/:id 点详情 404）
type: pitfall
domain:
- frontend
tags:
- router
- hidden-route
- constant-routes
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-03'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 菜单驱动的"全量清理"误删隐藏详情路由（/models/:id 点详情 404）

## 背景 / 现象

模型管理列表点"详情"跳到 `/models/23`，渲染**脱离 Layout 的裸 404 页**（无侧边栏、无页签），但视图文件 `views/models/detail.vue` 明明存在。

## 根因

`sys_menu` 只登记**可见菜单**，"列表 → 详情"这类下钻路由（`/models/:id`）从来不在菜单表里。M10 把 `constantRoutes` 里的业务路由全删、改由 `/auth/menus` 驱动时，**连带删掉了这条只能靠静态表存在的隐藏路由**；于是 `/models/23` 落到通配兜底 `/:pathMatch(.*)*` → 404 组件（该组件是裸路由，所以整个 Layout 都消失，这是"脱离 Layout 的 404"的典型指纹，可与"Layout 内 404 组件"区分）。

## 解决方案

把隐藏详情路由放回 `constantRoutes`，且**必须排在通配兜底之前**：

```js
{
  path: '/models/:id',
  component: Layout,
  hidden: true,
  children: [
    { path: '', component: () => import('@/views/models/detail.vue'),
      name: 'ModelDetail', meta: { title: '模型详情', activeMenu: '/models' } }
  ]
}
```

- `meta.activeMenu: '/models'` 让侧边栏仍高亮列表页（`Sidebar/index.vue` 优先读 `meta.activeMenu`）；
- 子路由 `name` 必须与组件 `<script setup name="ModelDetail">` 一致，否则 `AppMain` 的 `<keep-alive :include="cachedViews">` 缓存失效；
- 面包屑会是"首页 / 模型详情"（详情不在菜单树里，无中间层级），这是预期。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「菜单驱动的"全量清理"误删隐藏详情路由（/models/:id 点详情 404）」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

把路由从静态表迁到后端菜单驱动时，**先枚举所有 `views/**` 下非 `index.vue` 的页面与所有 `router.push('/xxx/...')` 调用**，逐条确认新来源能覆盖；菜单表覆盖不到的（详情页、下钻页、向导页）必须保留在 `constantRoutes` 并标 `hidden: true`。

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
