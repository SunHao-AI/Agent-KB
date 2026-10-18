---
id: kb-20261012-7959
title: 生产 lifespan 连接池 warm-up：消除首请求冷启动 p99
type: pitfall
domain:
- backend
tags:
- connection-pool
- warm-up
- p99
- cold-start
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-05'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# 生产 lifespan 连接池 warm-up：消除首请求冷启动 p99

## 背景 / 现象

（自本条根因段提取）生产首请求 p99 明显偏高（测试环境同款接口在加 warm-up 前测得 389.54ms），部署/重启后的第一批请求最慢，后续请求恢复正常。

## 根因

**根因**：FastAPI 生产首请求的 p99 高，源于 SQLAlchemy 连接池在首个请求时才首次建连（数据库握手/TLS/PRAGMA 开销一次性全落在首请求内）。测试 conftest 里加 warm-up 后 `GET /v1/clients (empty)` 的 p99 由 389.54ms 降到 24.81ms，但那只覆盖测试，生产 lifespan 未做同样预热。

## 解决方案

**方案**：在生产 lifespan（认证库探活之后）对 `QueuePool` 类型的连接池做预铺连接——`min(pool.size(), 3)` 个连接各发一次 `SELECT 1`：

```python
# ── 连接池 warm-up（P-2）──
from sqlalchemy.pool import QueuePool

for _eng in (engine,):
    if isinstance(_eng.pool, QueuePool):
        for _ in range(min(_eng.pool.size(), 3)):
            try:
                with _eng.connect() as conn:
                    conn.execute(text("SELECT 1"))
            except Exception as e:
                print(f"\033[1;33m连接池预热失败: {e}\033[0m")
                break
```

## 验证

原文实录: 测试 conftest 加 warm-up 后 `GET /v1/clients (empty)` 的 p99 由 389.54ms 降到 24.81ms(生产 lifespan 按同款方案预热)。

## 适用边界与反例

**要点**：

- 必须用 `isinstance(..., QueuePool)` 判定，**跳过** `StaticPool`（SQLite 单连接无池、预热无意义）。
- 预热连接数取 `min(pool.size(), 3)`，避免启动时过度开连接；失败只打印告警并 `break`，**不能**因预热失败阻断应用启动。
- 打开连接后自动交还池，预热建立的是"可用连接"，首请求复用，冷启动开销被前移到启动阶段。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
