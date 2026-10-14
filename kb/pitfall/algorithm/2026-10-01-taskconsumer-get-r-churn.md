---
id: kb-20261013-348e
title: TaskConsumer 每秒轮询放大 `_get_r` 每次新建连接池：空闲期每秒 churn 一个池（第四十八轮）
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/启动失败回写链路.md
---

# TaskConsumer 每秒轮询放大 `_get_r` 每次新建连接池：空闲期每秒 churn 一个池（第四十八轮）

## 背景 / 现象

**E2E 观测口径**（值得复用）：`redis-cli info clients` 的 `connected_clients` 差值——修复前模拟 100 次 lpop 后连接数≈+100（旧池 socket 挂到进程退出），修复后 +1（单池复用）。这比读代码断言"复用了"硬得多。

## 根因

`Redis._get_r()` 每次调用都新建 `ConnectionPool` + `Redis` client，旧池 socket 全靠 GC 回收。低频调用时问题被掩盖；TaskConsumer 空闲期每秒 lpop 一次，把「现场构造池」从低频问题放大成每秒 churn——池化对象生命周期与调用频率错配，形成 fd/GC 慢性抖动。

## 解决方案

`_get_r` 按 `(host, port, password, db)` 缓存池（双检锁，消费线程与请求线程可能并发首建）；`Redis` client 是池上的轻量包装，每次新建无害、不必缓存。

## 验证

E2E 观测口径（值得复用）：`redis-cli info clients` 的 `connected_clients` 差值——修复前模拟 100 次 lpop 后连接数≈+100（旧池 socket 挂到进程退出），修复后 +1（单池复用）。这比读代码断言"复用了"硬得多。

## 适用边界

- 池化对象（ConnectionPool/Engine/Session）必须进程级复用，**"每次操作现场构造"在轮询型调用方（lpop/sleep 循环）手里会从低频问题放大成每秒问题**——审资源类代码时先找调用方的调用频率，别按"调用点看起来不多"直觉判断；

- 缓存 key 必须含全部路由参数（host/port/password/db），漏一项在多实例/测试改配场景就是串库事故；配置可变性测试（改 host 必须换池）要与复用测试成对写。

## 参考

- 源记录: `docs/known-pitfalls/engine/启动失败回写链路.md` 「TaskConsumer 每秒轮询放大 `_get_r` 每次新建连接池：空闲期每秒 churn 一个池（第四十八轮）」
