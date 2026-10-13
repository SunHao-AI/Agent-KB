---
id: kb-20261012-7607
title: 根级叶子菜单（首页）绕过 Layout 导致首页无侧边栏/顶栏
type: pitfall
domain:
- frontend
tags:
- dynamic-route
- layout
- build-routes
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-03'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 根级叶子菜单（首页）绕过 Layout 导致首页无侧边栏/顶栏

## 背景 / 现象

登录后落地 `/index`，页面没有侧边栏、顶栏、面包屑、页签栏，两张卡片直接铺满整个浏览器窗口；而 `/algorithms` 等业务页都在 Layout 框架内。首页组件 `views/index/index.vue` 最外层明明写了 `div.app-container`，样式却不是问题。

## 根因

`store/modules/permission.js` 的 `buildRoutes` 用 `isRoot = !rawPath.startsWith('/')` 判定"是否挂 Layout"。菜单 Seed 里 M100 首页是 `('M100', 0, '首页', 'C', '/index', NULL, 'dashboard', 1)` —— path 是**绝对路径** `/index`，于是 `isRoot=false`，直接以视图组件注册成**顶级裸路由**，在 `App.vue`（只有一个裸 `<router-view/>`）下全屏渲染。业务页之所以正常，是因为它们挂在 M200/M300/M400 这些 `path=NULL`（被合成占位路径 `/m200` 并挂 `loadLayout`）目录节点的 children 下。判定"挂不挂 Layout"看的是 **path 形态**，而不是 **菜单层级**，这是错配。

## 解决方案

把判定依据改为"顶级 + 无子节点 + 绝对 path"，为该节点补一层**仅用于 redirect 的合成外壳**（复用现有 `menuCode` 占位路径机制），真实视图降为 children：

```js
if (isTop && !m.children?.length && rawPath.startsWith('/')) {
  const child = buildRoutes([m], false)[0]   // isTop=false 防递归自嵌套
  const synthesized = `/${(m.menuCode || m.name || 'sub').toLowerCase()}`
  return { path: synthesized, name: m.name, component: loadLayout, redirect: rawPath,
           meta: { icon: m.icon, perms: m.perms || [] },  // 外壳不放 title
           children: [child] }
}
```

四个配套要点：
1. **外壳 `path` 必须是 `menuCode` 合成路径**（`/m100`）而不是 `rawPath` —— 否则外壳与子级同为 `/index`，形成自嵌套。
2. **外壳 `meta` 不放 `title`** —— 面包屑按 `meta.title` 过滤层级，外壳无 title 才不会多出一级。
3. **Seed 里根级单页 `component` 为 NULL** —— 用 `PATH_COMPONENT_FALLBACK = { '/index': 'index/index' }` 按 path 兜底解析视图，不要再在 `buildRoutes` 里加 `path === '/index'` 写死特例。
4. **侧边栏不会重复** —— `SidebarItem.hasOneShowingChild` 对单子节点渲染 `el-menu-item` 并取 `onlyOneChild.meta`（即子级的标题与图标），`resolvePath` 对绝对子路径直接返回不拼 `basePath`，因此"首页"入口照常显示且高亮正确。

连带修复见下一条"动态路由绝对子路径不可与 basePath 拼接"；同时需把 `Breadcrumb/index.vue` 的 `isDashboard` 由 `name === 'Index'` 改为同时认本项目首页名 `HomeDashboard`，否则首页面包屑会渲染成"首页 / 首页"。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
