---
id: kb-20261013-0572
title: '`el-tag` 的 type 没有 `error`，复用 el-alert 的映射触发 Invalid prop 告警'
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-03'
updated: '2026-10-13'
review_by: '2027-01-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/授权状态与全局横幅.md
---

# `el-tag` 的 type 没有 `error`，复用 el-alert 的映射触发 Invalid prop 告警

## 背景 / 现象

expired 态授权页/设置页控制台告警 `Invalid prop: validation failed for prop "type". Expected one of ["primary", "success", "info", "warning", "danger"], got value "error"`。

## 根因

`el-alert` 与 `el-tag` 的类型枚举**不同**——alert 用 `error`，tag 只有 `primary/success/info/warning/danger`。store 里一个 `bannerType` 同时喂给两者，alert 正常、tag 越界。

## 解决方案

store 拆两个 getter，映射表分开维护，页面按组件取用：

```javascript

const BANNER_TYPE = { grace: 'warning', expired: 'error' }   // el-alert

const TAG_TYPE = { valid: 'success', grace: 'warning', expired: 'danger' } // el-tag

```

`bannerType` 给 alert/banner，`tagType` 给 el-tag；`license.spec.js` 增一条用例锁死"expired → tagType=danger 且 bannerType=error"。

## 验证

`license.spec.js` 增一条用例锁死"expired → tagType=danger 且 bannerType=error"。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/授权状态与全局横幅.md` 「`el-tag` 的 type 没有 `error`，复用 el-alert 的映射触发 Invalid prop 告警」
