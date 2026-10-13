---
id: kb-20261012-8311
title: el-link 的 `underline` 属性传布尔值触发弃用警告
type: pitfall
domain:
- frontend
tags:
- el-link
- deprecation
- element-plus
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-08'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表格网格与组件显示.md
---

# el-link 的 `underline` 属性传布尔值触发弃用警告

## 背景 / 现象

浏览器控制台出现 Element Plus 弃用警告：`ElementPlusError: [el-link] [API] The underline option (boolean) is about to be deprecated in version 3.0.0, please use 'always' | 'hover' | 'never' instead.`

## 根因

Element Plus 3.0.0 起 `el-link` 的 `underline` 属性不再接受布尔值（`true`/`false`），只接受字符串 `'always' | 'hover' | 'never'`。项目中 `:underline="false"` 传布尔值，触发 `useDeprecated` 警告；当前版本仍可渲染，但升级到 3.0.0 后该写法会失效。

## 解决方案

把布尔值替换为等价的字符串：
- `:underline="false"` → `underline="never"`（不显示下划线）
- `:underline="true"` → `underline="always"` 或 `underline="hover"`

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

`views/models/index.vue` 引用数列 `el-link :underline="false"` 已改为 `underline="never"`；项目其它用法（`FileUpload/index.vue`、`ExcelImportDialog/index.vue`、`views/models/index.vue` 第 79 行）本就是字符串 `underline="never"`，无需改动。

凡 Element Plus 组件属性由 boolean 升级为枚举/字符串的（如 `underline`），统一使用字符串写法，避免升级到 3.x 后渲染失效。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格网格与组件显示.md`
