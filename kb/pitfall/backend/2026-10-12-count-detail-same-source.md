---
id: kb-20261012-e009
title: '"计数"与"明细"必须同源委托，不可各写一份聚合口径（逐客户端待回执端点）'
type: pitfall
domain:
- backend
tags:
- aggregation
- receipt
- drift
scope: universal
status: accepted
severity: high
confidence: verified
created: '2026-10-12'
updated: '2026-10-13'
review_by: '2027-04-11'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/密钥与授权轮换.md
---

# "计数"与"明细"必须同源委托，不可各写一份聚合口径（逐客户端待回执端点）

## 背景 / 现象

> 面向：Overview 聚合计数升级为逐客户端明细端点（setting 仓 `_pending_receipt_total` → `_pending_receipt_rows`，2026-10-12 授权管理继续优化 S3）。

**现象**：Overview 原本只有 `pending_receipt_total`（曾签发 .zluf 且其后再无回执的客户端**数**）。要出逐客户端明细时，若另起一个函数独立算一遍"哪些客户端待回执"，就是同一口径写两份。实际初版明细函数只按 `zluf_issue` 记时刻，**漏了"issue 之后又 receipt 应移出"**——已回执客户端仍被计入，与既有计数口径直接矛盾（测试 `assert [2,1]==[1]` 才暴露）。

## 根因

"待回执"口径(最后是 zluf_issue 才入选, issue 后又 receipt 须移出)被计数与明细两份独立实现各自表达; 两份算法之间无任何机制强制同步, 新写的明细只匹配了"存在 zluf_issue"而漏掉排除条件, 口径漂移随之发生.

## 解决方案

**方案**：明细 `_pending_receipt_rows(db)` 是**唯一**口径实现（升序遍历审计，`last_action[cid]=(action,created)` 后写覆盖前写，仅"最后是 zluf_issue"入选）；计数 `_pending_receipt_total` 退化为 `len(_pending_receipt_rows(db))`，绝不自己再算。前端 ReceiptDrawer 从"取列表首页 page_size=100 人工比对"改为消费新端点（超 100 客户端也完整可见），端点必须输出 `app_key`（上传回执的请求体键，明细缺它前端拿不到上传目标）。

## 验证

原文实证：初版口径矛盾由测试 `assert [2,1]==[1]` 暴露；修复后回归锁一个用例同时断言 `rows` 明细、`total==len(rows)`、端点 `items` 三者同源。

## 适用边界与反例

**要点**：
- 静态段路由 `/pending-receipts` 必须注册在 `/{client_id}` 之前（同 overview，literal 不自动胜出）。
- 回归锁：一个用例同时断言 `rows` 明细、`total==len(rows)`、端点 `items` 三者同源，任何一处口径漂移立即红。
- 同族教训：任何"聚合数 + 明细列表"并存处，明细是实现、计数是 `len(明细)`；两份独立算法 = 迟早漂移。

## 参考

- 源记录: `docs/known-pitfalls/backend/密钥与授权轮换.md`
