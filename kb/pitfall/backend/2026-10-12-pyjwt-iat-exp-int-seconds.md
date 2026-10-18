---
id: kb-20261012-9d79
title: PyJWT iat/exp 不能传 datetime
type: pitfall
domain:
- backend
tags:
- pyjwt
- jwt
- iat
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/鉴权与会话.md
---

# PyJWT iat/exp 不能传 datetime

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`MySQLAuthProvider._encode` 用 `datetime.now()` 当 `iat`，签发后第一次 `jwt.decode` 即抛 `ImmatureSignatureError: The token is not yet valid (iat)`；访问 token / 刷新 token 全部 401。

## 根因

**根因**：PyJWT 内部 `datetime.fromtimestamp(iat) <= datetime.utcnow()`——`datetime.fromtimestamp(float)` 正常，但比较分支里 `naive<=aware` 在 Py3 会抛 `TypeError` 走 `_validate_iat(datetime.now())` 检测路径返回假值，最终被错误判为 "token 未生效"。本质是 PyJWT 假设 `iat/exp` 是 Unix 秒 int。

## 解决方案

**解决**：`_encode` 改用 `int(time.time())` 作为 iat/exp 秒数；不能传 Python `datetime` 对象：
```python
def _encode(self, payload, secret, ttl):
    now_ts = int(time.time())
    payload.update({"exp": now_ts + ttl, "iat": now_ts})
    return jwt.encode(payload, secret, algorithm="HS256")
```

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/鉴权与会话.md` :: 「PyJWT iat/exp 不能传 datetime」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例





源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/鉴权与会话.md` :: 「PyJWT iat/exp 不能传 datetime」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

