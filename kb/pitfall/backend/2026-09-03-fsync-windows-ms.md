---
id: kb-20261013-fa23
title: 并发线性放大的真凶是单调时钟每请求 fsync（Windows 挂载卷 150ms/次）——归因必须拆到最内层函数
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-03'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/授权三态与离线容器.md
---

# 并发线性放大的真凶是单调时钟每请求 fsync（Windows 挂载卷 150ms/次）——归因必须拆到最内层函数

## 背景 / 现象

`POST /v1/sse/ticket` 串行 p50 288ms，并发 c1 340 → c5 1141 → c10 p50 1902ms（29/30 超 1s），耗时随并发近线性放大；而 handler `duration` 仅 4~15ms、容器 CPU 3%、`/health` 端到端 3~5ms。

## 根因

```

jwt.decode only (RS256)          [0.6, 0.4, 0.4, 0.3, 0.4, 0.4]   ← 密码学本尊: 0.4ms

MonotonicClock.now()             [83.6, 134.6, 134.4, 123.9, 135.1, 155.6]  ← 真凶

Throttled.now() (同秒跳过 save)   [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]   ← 去掉落盘后归零

```

`MonotonicClock._save()` 是"写 tmp + **`os.fsync`** + `os.replace`"，数据目录挂在 **Docker Desktop 的 Windows 挂载卷**上 → 单次 83~155ms。而 `now()` **每一秒内的每次调用都重复落盘同一个值**：授权链路每请求调 2 次（`verify` 的 iat 检查 + `resolve_state` 的到期判定）= 单请求 2 次 fsync；`_SAVE_LOCK` 是**类级全局锁**，把所有请求的落盘串成一条队 → 并发**线性放大**的真凶（也解释了"线程池更慢"：线程越多，抢锁 + 卷上 fsync 越惨）。

## 解决方案

1. **`MonotonicClock._save` 同秒去重（治本，两仓同步）**：类级 `_PERSISTED: dict[storage_path → 已落盘秒值]`，待写值与已落盘值相同直接 return；判断与写入同在 `_SAVE_LOCK` 内，保证同秒最多落一次盘。**防回拨语义不变**（跨秒才写，重启后读到的仍是最近已落盘秒值）。效果：`verify()` 122~283ms → **0.4ms**，`now()` → **0ms**。

2. 决策记忆 + single-flight、`_persist_state` 稳态跳过、`_load_config` 快照（`backend/license/config_cache.py`）：在真根因之上进一步把稳态非白名单请求压到 handler 5ms 级，仍是有效资产（但**不是**当初以为的"扛住 GIL"）。

端到端（浏览器已登录会话，冷缓存多轮）：串行 p50 288→82ms、c3 682→175ms、c5 1141→278ms；后端自身 `duration` 稳态 4~6ms。残余波动属浏览器 HTTP/1.1 每域名 6 连接排队，非服务端。

## 验证

组件级计时：`jwt.decode` 仅 0.4ms、`MonotonicClock.now()` 83~155ms、去掉落盘后 `Throttled.now()` 归零。端到端（浏览器已登录会话，冷缓存多轮）串行 p50 288→82ms、c3 682→175ms、c5 1141→278ms；后端自身 `duration` 稳态 4~6ms。

## 适用边界

- **归因必须拆到最内层操作，不能停在"某函数慢"**。本案 `verify()` 慢 300 倍的真凶藏在它调用的 `clock.now()` 里；只要测的是"函数"而非"操作"，就会把别人的 IO 记成自己的 CPU。**下结论前先问：这个函数内部还调了谁？**

- **怀疑 GIL 之前先怀疑 IO**。"线程池不加速甚至变慢"更常见的原因是：① 全局/类级锁把并行又串回去了；② 慢的是卷上 fsync/网络等外部等待。真 GIL-bound 需要**同一段代码串行 vs 并行的吞吐对比 + 内部无锁无 IO**两个前提才成立。

- **`os.fsync` 在 Docker Desktop (Windows/macOS) 挂载卷上是 100ms 量级**，绝不能出现在每请求热路径。落盘类"基准/水位线/游标"必须做**值未变不写**或节流；需要高频单调时间用 `time.monotonic()`（进程内），磁盘只存跨重启的锚点。

- **类级/全局锁 = 并发天花板**。写热路径前先问：这把锁的临界区里有没有 IO？有的话它决定了全站吞吐。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权三态与离线容器.md` 「并发线性放大的真凶是单调时钟每请求 fsync（Windows 挂载卷 150ms/次）——归因必须拆到最内层函数」
