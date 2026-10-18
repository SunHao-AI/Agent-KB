---
id: kb-20261012-e0b4
title: HMAC 签名 canonical 的 path 必须不含 query string（2026-09-18）
type: pitfall
domain:
- backend
tags:
- hmac
- signature
- canonical
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-18'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/鉴权与会话.md
---

# HMAC 签名 canonical 的 path 必须不含 query string（2026-09-18）

## 背景 / 现象

> 面向：`flysee-video-setting` 的 HMAC 出站签名通道（客户端带 `X-App-Key/X-Timestamp/X-Nonce/X-Signature` 调用 `/v1/licenses/*`），服务端 `backend/middleware/signature.py` + `backend/crypto/signature.py`。

**现象**：同一把 app_secret、同一个 `sign_request()`，POST 验签通过 200，GET（URL 带 `?app_key=...`）恒定 `401 签名验证失败`。排查时容易误判成"GET 的 body_hash 处理有问题"。

## 根因

**根因**：canonical 是 `f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"`，服务端拼 `path` 用的是 **`request.url.path`（不含 query string）**；调用方若图省事把完整相对 URL（`/v1/licenses/status?app_key=xxx`）当 path 传进去，canonical 就不同 → 签名不匹配。与 body、时间戳、nonce 都无关。

## 解决方案

**解决**：签名时 `path` 传**纯路径**（`/v1/licenses/status`），query 只拼在真实请求 URL 上、不参与 canonical：

```python
# ✅ query 不参与签名
sig = sign_request(secret, "GET", "/v1/licenses/status", ts, nonce, "")
urllib.request.urlopen(BASE + f"/v1/licenses/status?app_key={ak}")
```

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/鉴权与会话.md` :: 「HMAC 签名 canonical 的 path 必须不含 query string（2026-09-18）」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

**防踩**：
- 签名与发送必须用**同一份字节**（body 同理：签之前算好的 `body_bytes` 直接当请求体，别 `json.dumps` 两次）；
- 新增带 query 的签名接口时，签名侧与验签侧都要走同一个契约，别一侧 `url.path` 一侧 `url`；
- 断言"签名正确"的测试要**同时覆盖带 query 的 GET**，否则这个坑只在联调时才炸。

## 参考

- 源记录: `docs/known-pitfalls/backend/鉴权与会话.md`
