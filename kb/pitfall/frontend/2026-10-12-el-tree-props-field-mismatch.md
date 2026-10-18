---
id: kb-20261012-e847
title: el-tree 字段名与后端响应/勾选 keys 不匹配导致"label 空白 + 勾选失效"
type: pitfall
domain:
- frontend
tags:
- el-tree
- field-mismatch
- snake-case
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# el-tree 字段名与后端响应/勾选 keys 不匹配导致"label 空白 + 勾选失效"

## 背景 / 现象

编辑角色/部门等"权限/菜单树"页面，弹层里 el-tree 所有节点 label 全部为空白（DOM `<span class="el-tree-node__label"></span>` 是空的），但 `label` 字段下拉/复选框的 checked 状态似乎是对的（事后排查发现是因为 list 接口本身带 `menu_codes`，勾选键恰好蒙对了）。

## 根因

element-plus el-tree 默认 `props = { label: 'label', children: 'children' }`，即读取节点对象上的 `label` 字段显示文字；本前端侧通过 `node-key` 给节点唯一标识，但在不同页面存在多种历史写法：
1. `node-key="menuCode"`（camelCase）
2. 后端 `/system/menus/tree` 实际返回 `menu_code`（snake_case）
3. 后端字段用 `menu_name`，没有 `label`

三者错位时就是「**label 空白（无 label 字段）+ 即便显式 `:props` 漏配 node-key 写错字段，`setCheckedKeys` 也找不到 node → 勾选失效**」。更隐蔽的是 el-tree `node-key` 的字段名要和**写 key 的那条数据本身的字段名**一致，不能与请求体（query/req）的命名风格绑定（本页同时存在 `menuCode` 与 `menu_code` 两种字段名）。

## 解决方案

- el-tree 显式给 `:props="{ label: 'menu_name', children: 'children' }"`（label 字段名按后端实际响应字段，不是页面变量名）
- `node-key` 字段名按后端响应的实际字段（与 `:props` 一致）
- 回显 `setCheckedKeys(ids)` 时 ids 的元素类型必须与 `node-key` 字段类型一致（一般 string）

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表格网格与组件显示.md` :: 「el-tree 字段名与后端响应/勾选 keys 不匹配导致"label 空白 + 勾选失效"」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

从列表接口已经带 `menu_codes` 字段的，`openEdit` 不必再调一次 `getRole`/`getXxx` 单独查详情，直接复用 row 数据即可，省一次网络往返。

- 凡前端 el-tree / 任何 element-plus 组件用 `:props` 配置，**字段名必须与后端响应里实际字段名一致（不是请求体/路由参数风格）**；后端若同时存在驼峰/蛇形两种风格（双协议），前端要明确以蛇形为准（FastAPI 默认输出）
- 节点 key、复选 keys 写 `setCheckedKeys` 前，先确认数据里该字段是否就是数组的 key（看后端 `_xxx_out` / 序列化层）
- el-tree 空白 + 勾选失效的组合坑通常单看 Node 层面都可能误判为 data 字段污染，但实际是字段名错配：检查元素类名 `el-tree-node__label` 是空字符串而非 undefined，对比该页面对应的后端 `/xxx/tree` 接口的实际响应

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
