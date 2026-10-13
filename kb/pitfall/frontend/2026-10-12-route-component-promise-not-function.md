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
updated: '2026-10-12'
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

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
