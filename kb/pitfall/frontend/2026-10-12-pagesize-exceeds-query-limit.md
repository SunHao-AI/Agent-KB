---
id: kb-20261012-f4c1
title: 前端分页参数不能超过后端 Query 上限
type: pitfall
domain:
- frontend
tags:
- pagination
- fastapi
- query-validation
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表单交互与数据绑定.md
---

# 前端分页参数不能超过后端 Query 上限

## 背景 / 现象

后端容器日志反复出现 `GET /v1/system/roles?pageNum=1&pageSize=200 422 Unprocessable Entity`，用户管理页角色下拉为空。

## 根因

后端 `/system/roles` 声明 `pageSize: int = Query(..., le=100)`，前端为"拉全量角色"传了 `pageSize=200`，被 FastAPI 参数校验拦截。

## 解决方案

前端请求后端分页接口前先确认 `le` 上限；角色/字典等小字典数据用 `pageSize=100` 拉取，或后端显式提供 `all=true` 非分页接口。不要在前端随意放大小于等于约束之外的 pageSize。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单交互与数据绑定.md`
