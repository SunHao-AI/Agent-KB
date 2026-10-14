---
id: kb-20261013-3069
title: 连接池 5+10=15 是硬瓶颈：并发一超容量即 QueuePool 超时雪崩，且雪崩会饿死 /health（停压后 143s 才恢复）
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-03'
updated: '2026-10-13'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/授权三态与离线容器.md
---

# 连接池 5+10=15 是硬瓶颈：并发一超容量即 QueuePool 超时雪崩，且雪崩会饿死 /health（停压后 143s 才恢复）

## 背景 / 现象

并发一超连接池容量（5+10=15）即 QueuePool 超时雪崩，且雪崩饿死 /health——停压后 143s 才恢复。

## 根因

`create_engine` 未显式设池参数，默认 5+10=15 远小于并发规模与 anyio 40 线程池；每个鉴权请求至少两次 DB 往返占用连接，并发一超 15 就整体排队。放大器是 `pool_timeout` 默认 30s 长于客户端 15s 超时——请求已失败而连接仍被僵尸请求占用满 30s，队列拖成数分钟；同步 `def` 端点与中间件又全挤同一 40 线程池，不碰 DB 的 `/health` 也被拖死。

## 解决方案

1. `database.py` 新增 `_pool_kwargs()`：按 uvicorn worker 数**分摊** MySQL `max_connections`(100) 预算（取 96 留运维直连余量），`pool_timeout` 30→**10s**（快速失败可重试，不再挂 30s 堆僵尸连接），`pool_recycle=3600`（< `wait_timeout`），仅对 `mysql` 方言生效（sqlite 测试返回 `{}`）。**关键算术**：每进程总连接 = 预算/workers，再拆 `pool_size`(70%)+`max_overflow`(余)——拆分只在 per_worker 内部做，`(pool_size+max_overflow)×workers` 恒 ≤ 预算。**朴素地"两者各自 /workers"会让单池峰值=1.6×预算/workers、prod 4 worker 相加≈153 击穿 100**，故抽成纯函数 + `tests/test_db_pool_budget.py` 钉死任意 worker 数下总量有界。

2. `main.py` lifespan 启动时 `current_default_thread_limiter().total_tokens = settings.ANYIO_THREAD_LIMIT`(128)——线程数 > DB 连接上限，让 **DB 池成为第一道有界闸门**（超容量快速失败，而非无限堆线程）。

3. `/health` 改 `async def`：健康检查永不占线程池，依赖劣化时仍能如实报活。

## 验证

getInfo conc=100 从 **0%→100% 成功（114 QPS/p99 1.7s）**、conc=150 仍 100%（116 QPS）；license-state conc=100 **0%→100%（73 QPS）**；**停压后首个 `/health` 143s→44ms**；近 3 分钟 QueuePool 报错 **0 条**；后端全量 **529 passed** + 新增池预算 4 用例。

## 适用边界

- **同步 SQLAlchemy + 同步 `def` 端点体系下，连接池/线程池是隐形硬上限，且默认值极小（池 15、线程 40）**。并发一旦越过"每请求 DB 往返数 × 池容量"就是**非线性雪崩**（不是变慢，是 0% 成功），且**白名单端点因共抢同一线程池而被拖下水**——所以"免鉴权的 /health 也崩"不代表授权逻辑有问题，而是全局池饥饿。**压测必须一路推到崩塌点**，只看 conc≤50 的"全 200"会完全漏掉悬崖。
放大器是 `pool_timeout` 默认 30s 长于客户端 15s 超时——请求已失败而连接仍被僵尸请求占用满 30s；同步 def 端点与中间件全挤同一 40 线程池，不碰 DB 的 /health 也被拖死。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权三态与离线容器.md` 「连接池 5+10=15 是硬瓶颈：并发一超容量即 QueuePool 超时雪崩，且雪崩会饿死 /health（停压后 143s 才恢复）」
