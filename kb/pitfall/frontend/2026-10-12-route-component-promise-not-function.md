---
id: kb-20261012-71d2
title: 动态路由 component 不能传 Promise 本身
type: pitfall
domain:
- frontend
tags:
- router
- lazy-load
- dynamic-import
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2026-11-01'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/路由与导航.md
---

# 动态路由 component 不能传 Promise 本身

## 背景 / 现象

浏览器控制台出现多条 `[Vue Router warn]: Component "default" in record with path "/m200|/m300|/m400" is a Promise instead of a function that returns a Promise`。

## 根因

`buildRoutes` 对目录节点写了 `component: loadLayout()`，立即调用动态 import 得到 Promise；Vue Router 需要的是懒加载函数 `() => import(...)`，不是 Promise 对象。

## 解决方案

布局组件传 `component: loadLayout`，不要加括号调用；业务视图由 `loadView(component)` 返回函数。新增动态路由时区分"函数引用"与"函数调用"。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「动态路由 component 不能传 Promise 本身」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/路由与导航.md` :: 「动态路由 component 不能传 Promise 本身」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
