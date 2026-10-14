---
id: kb-20261013-afcf
title: '`generateRoutes` 按角色置 hidden 时 `{...r}` 浅拷贝共享 `children` 引用——污染 `constantRoutes`
  影响下次登录'
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-25'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/概览页与操作入口一致性.md
---

# `generateRoutes` 按角色置 hidden 时 `{...r}` 浅拷贝共享 `children` 引用——污染 `constantRoutes` 影响下次登录

## 背景 / 现象

用户管理页立项实施（2026-10-09）：`generateRoutes` 按角色置 hidden 时对嵌套路由用 `{...r}` 浅拷贝，`children` 仍共享引用——写派生层属性即写穿 `constantRoutes` 模块级单例，污染影响下次登录。

## 根因

权限过滤是**对共享不可变常量的派生写**。`{...r}` 是浅拷贝；Vue Router 的 `RouteRecordRaw` 是嵌套结构（`children` 数组 + 元素对象），任何一层没新建，写派生层的属性就是写原对象。`store` 持有派生数组、`constantRoutes` 模块级单例跨登录存活（Pinia 登出不清模块），写穿即永久污染。

## 解决方案

逐层新建——[generateRoutes](file:///d:/WorkPlace/Pycharm/flysee_video_web/frontend/src/store/modules/permission.js) 内递归 `filter`：每层 `{ ...r }` 新建父对象，`children` 存在则**递归产出新数组 + 新子对象**（任意深度，不止一层），绝不 `r.children[i].hidden = ...`。spec 加**常量纯度断言**：跑完 `generateRoutes(['user'])` 后断言 `constantRoutes` 上 `/users` 的原始对象 `hidden === undefined`，锁死"过滤不改原对象"。

## 验证

spec 加**常量纯度断言**：跑完 `generateRoutes(['user'])` 后断言 `constantRoutes` 上 `/users` 的原始对象 `hidden === undefined`，锁死"过滤不改原对象"。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。
凡对模块级常量/冻结配置做"按用户态派生视图"，拷贝深度必须 ≥ 写入深度；共享常量的派生逻辑必须配"原对象未被污染"的纯度断言，否则缺陷只在"换账号重登"低频路径出现，日常自测 100% 不可见。

## 参考

- 源记录: `docs/known-pitfalls/frontend/概览页与操作入口一致性.md` 「`generateRoutes` 按角色置 hidden 时 `{...r}` 浅拷贝共享 `children` 引用——污染 `constantRoutes` 影响下次登录」
