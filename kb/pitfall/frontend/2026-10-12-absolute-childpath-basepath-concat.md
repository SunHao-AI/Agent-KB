---
id: kb-20261012-3ad5
title: 动态路由绝对子路径不可与 basePath 拼接（全局搜索 404）
type: pitfall
domain:
- frontend
tags:
- router
- path-concat
- header-search
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-03'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 动态路由绝对子路径不可与 basePath 拼接（全局搜索 404）

## 背景 / 现象

顶栏全局搜索选中"规则"跳 `/m200/algorithms`、选中"首页"跳 `/m100/index`，都命中兜底 404；侧边栏点同一个菜单却是好的。

## 根因

本项目动态路由的子节点用**绝对 path**（后端菜单 `path='/algorithms'`，挂在合成外壳 `/m200` 下，靠 vue-router 4 的"子路由可用绝对 path"特性工作）。`components/HeaderSearch/index.vue` 的 `generateRoutes` 无条件 `getNormalPath(basePath + p)` 拼路径，对绝对子路径就算出 `/m200/algorithms`。`SidebarItem.resolvePath` 早就处理了这个分支（`routePath.startsWith('/')` 直接返回），但 `HeaderSearch` 没跟上；`TopNav.childrenMenus` 在 `navType=2`（混合菜单）下有同类问题，且带 `router.children[i].path = ...` 对象副作用。

## 解决方案

凡递归遍历路由树并累加 `basePath` 的地方，都必须先判断**原始 `r.path`** 是否以 `/` 开头，是则直接使用、不拼前缀：

```js
const isAbs = typeof r.path === 'string' && r.path.startsWith('/')
const p = isAbs ? r.path : '/' + (r.path || '')
const full = getNormalPath(isAbs ? p : basePath + p)
```

两个坑：判定对象必须是**原始 `r.path`**，不能判定已补斜杠的 `p`（`p` 恒以 `/` 开头，会让所有层级都被当成绝对路径）；HTTP 外链仍由 `isHttp(r.path)` 优先短路。**新增任何遍历路由树生成路径的组件（菜单、搜索、面包屑、Tab 补全）时，一律照抄 `SidebarItem.resolvePath` 的约定**，不要另起一套拼接。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「动态路由绝对子路径不可与 basePath 拼接（全局搜索 404）」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「动态路由绝对子路径不可与 basePath 拼接（全局搜索 404）」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
