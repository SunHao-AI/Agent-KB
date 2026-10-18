---
id: kb-20261013-bf03
title: 交叉验证后端时参数漂移：curl 用错参数名被 FastAPI 静默忽略，"前后端不一致"是问错了问题
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/走查与自动化验证陷阱.md
---

# 交叉验证后端时参数漂移：curl 用错参数名被 FastAPI 静默忽略，"前后端不一致"是问错了问题

## 背景 / 现象

走查测快速连点翻页竞态：前端停在第 3 页，首条任务 ID 是 `d4155e4082ac481ca402`；用 curl 直连 `GET /v1/tasks?page=3&pageSize=10` 拿到的首条却是 `0e399a60858f4454b8cf`——两者不一致，看上去坐实了"翻页显示旧页数据"的竞态缺陷。

## 根因

- 前端真实请求是 `?pageNum=3&pageSize=10`（network 面板可见），我 curl 凭记忆写成 `?page=3`。

- **FastAPI 对未声明的 query 参数静默忽略**（不报 422），`page=3` 等于没传 → 后端按默认 `pageNum=1` 返回第 1 页。

- 我拿"后端第 1 页"对比"前端第 3 页"，差异完全是我构造出来的。改用 `pageNum=3` 后首条精确一致，竞态不存在（latest-wins 守卫本来就在工作）。

- 同场加映半截坑：响应数据字段我猜的是 `data.list`，实际是 `data.rows`——PowerShell 里 `$null[0]` 报 "Cannot index into a null array" 才暴露。**猜字段名/参数名前先看一眼真实响应**。

## 解决方案

- **交叉验证前，先从 `browser_network_requests` 抓浏览器真实请求 URL，逐字复制 path+query 给 curl**——不要凭对代码的印象重写参数。

- **FastAPI"未知 query 参数静默忽略"是验证假象的放大器**：它不会用报错提醒你问错了问题。对比结果异常时，先怀疑"两边问的是不是同一个问题"（参数名、分页起点、排序参数、默认时区），再怀疑被测系统。

- "不一致"永远先自查验证脚本，再报缺陷：本轮若直接按"竞态缺陷"开工修复，会修一个不存在的问题。

## 验证

真相取证：前端真实请求是 `?pageNum=3&pageSize=10`（network 面板可见），curl 凭记忆写成 `?page=3`——FastAPI 对未知 query 参数静默忽略，两边拿到的本就是不同查询。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/走查与自动化验证陷阱.md` 「交叉验证后端时参数漂移：curl 用错参数名被 FastAPI 静默忽略，"前后端不一致"是问错了问题」
