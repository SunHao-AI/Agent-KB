---
id: kb-20261012-5532
title: 菜单已声明 component 但视图未创建，路由匹配仍 404（/licenses 授权续期）
type: pitfall
domain:
- frontend
tags:
- menu
- view-missing
- load-view
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

# 菜单已声明 component 但视图未创建，路由匹配仍 404（/licenses 授权续期）

## 背景 / 现象

侧边栏"客户端/许可证 → 授权续期"菜单正常显示（M303 来自后端 `/auth/menus`），点击后 URL 变为 `/licenses` 且路由**命中成功**（面包屑、页签都正确），但内容区渲染 404 组件；不会落到通配兜底，所以 Layout 仍在。

## 根因

动态路由链路 `buildRoutes → loadView(component)` 用 `import.meta.glob('@/views/**/*.vue')` 按 `/views/<component>.vue` 后缀查找视图模块，查不到时**静默回退到 404 组件**。Seed 里 M303 声明了 `component='licenses/index'`，但 `frontend/src/views/licenses/index.vue` 从未创建——菜单、路由、权限三层都是"纸面存在"，只有视图文件缺失。这类缺陷后端菜单校验发现不了，pytest 也测不到（前端文件不存在不影响任何接口）。

## 解决方案

（补全整条链路，缺一层都会 404/403）：
1. 新建 `frontend/src/views/licenses/index.vue`，`<script setup name="Licenses">`；
2. `store/modules/permission.js` 的 `COMPONENT_NAME_MAP` 登记 `'licenses/index': 'Licenses'`——**动态路由的 route.name 取自该映射**，不登记则 route.name 回退为组件文件名 `index`，与组件 name `Licenses` 不一致，`keep-alive :include` 缓存失效（页签切换闪白，参见"登录鉴权与keep-alive"）；
3. 管理端没有现成数据来源，需同步补后端：`GET /v1/admin/licenses`（列表）、`GET /v1/admin/licenses/{client_id}`（详情）、`POST /v1/admin/licenses/{client_id}/renew`（手动续期），复用 `license_service` 的续期校验与错误码（E_LICENSE_001/002→403）；
4. 权限节点 Seed 补 F 型按钮 F30301 `license:list` / F30302 `license:renew`（父=M303），并给角色关联（SUPER_ADMIN/ADMIN 双权限，OPERATOR/READONLY 仅 `license:list`）；已建库用 `INSERT IGNORE` DML 回填，无需 DDL。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

新增/修改 Seed 菜单时必须同步核对四件事——① `views/<component>.vue` 文件存在；② `COMPONENT_NAME_MAP` 已登记且 name 与 `<script setup name>` 一致；③ 页面所需接口在后端存在且走 `require_perm`；④ F 型权限节点与角色关联齐全。浏览器冒烟验收是唯一能兜住"视图缺失"这类缺陷的手段（接口测试全绿也可能页面 404）。

## 参考

- 源记录: `docs/known-pitfalls/frontend/路由与导航.md`
