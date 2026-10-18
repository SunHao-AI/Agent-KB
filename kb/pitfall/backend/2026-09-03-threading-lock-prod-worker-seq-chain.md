---
id: kb-20261013-647f
title: 哈希链履历的追加锁是 `threading.Lock`：prod 4 worker 并发追加 86% 撞 seq、整链被签发侧判 chain_broken
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

# 哈希链履历的追加锁是 `threading.Lock`：prod 4 worker 并发追加 86% 撞 seq、整链被签发侧判 chain_broken

## 背景 / 现象

| 组 | 跨进程锁 | 总行数 | dup_seq | chain_ok |

| --- | --- | --- | --- | --- |

| 修复前（`threading.Lock` 单层） | 无 | 200 | **172（86% 撞号）** | **false（断链）** |

| 修复后（sidecar flock） | 有 | 200 | **0** | **true** |

现场表现却是**完全静默**：每个写者都返回成功、无任何日志告警。直到回执回传, 签发侧 `ingest_client_events` 对新 seq 做续接校验（`seq == last.seq+1 且 prev_hash == last.hash`）才判 `chain_broken`——**反篡改审计在干净部署上误报"履历疑似被篡改"**。

## 根因

1. **锁的级别与部署形态错配**：`append_event` 用模块级 `threading.Lock` 串行化"读末行→追加"，它只覆盖**本进程多线程**；而 prod 镜像 `Dockerfile` 是 `uvicorn --workers 4`, **4 个 OS 进程共享同一 `data/license/license_ledger.jsonl`**。两进程各自 `_tail()` 读到 `(N, H)` → 都写 `seq=N+1 / prev_hash=H` → 重复 seq + 后写者 prev_hash 与前序 hash 脱节。

2. **写者恰好会在同一瞬间撞车**：调度器续期（`EV_RENEW_OK/FAIL`, Redis SETNX 单 worker 执行）与**任意 worker 线程池里的中间件** `_persist_state`（`enter_grace/expired`、`hw_mismatch` 去重首记）可同时触发；手动「立即同步」再引入第五个写者。

3. **同一份代码的"多进程自觉"不一致**：调度器注释明确写着「uvicorn --workers 4 时只有一个 worker 真正执行」（Redis SETNX），说明多进程部署是被意识到的——但 ledger 的锁没有做同样的推理。**这类"同仓不同文件对部署形态假设不一致"的坑，静态读代码极易滑过**。

4. 为什么一直没炸：dev 是单 worker + `--reload`, 结构上不可能复现——**dev 单进程是并发类 bug 的永久盲区**。

## 解决方案

`ledger.py` 新增 `_process_lock()`：**sidecar 文件 `flock(LOCK_EX)`** 把"读末行→算链→追加"整段临界区跨进程串行化；`append_event` 改 `with _lock, _process_lock():`（进程内锁先挡同进程线程, flock 再挡跨进程）。降级优先：`fcntl` 不存在（Windows 仅 dev 单进程, `threading.Lock` 已足）直接放行；拿锁超时(2s)/句柄不可得一律**放行**——绝不为履历写入阻塞业务请求（与既有"写失败降级 no-op"同理念）。

回归：`test_multi_process_append_keeps_chain_intact`（8 进程 fork + `_tail` 加 5ms 延迟撑开窗口，断言 `total=200 / 无重复 seq / verify_chain=True`；`fcntl is None` 自动 skip）、`test_process_lock_is_noop_without_fcntl`、`test_append_single_thread_still_sequential`。license 四文件 **81 passed, 1 skipped**；dev 后端 bind-mount 热重载后 `/health` 200。

## 验证

对照实测：修复前（`threading.Lock` 单层、无跨进程锁）200 行 dup_seq=172（86% 撞号）、chain_ok=false；修复后（sidecar flock）200 行 dup_seq=0、chain_ok=true。回归：`test_multi_process_append_keeps_chain_intact`（8 进程 fork + `_tail` 加 5ms 延迟撑开窗口，断言 `total=200 / 无重复 seq / verify_chain=True`）；license 四文件 **81 passed, 1 skipped**。

## 适用边界

- **看到模块级 `threading.Lock` 保护"读共享文件→改→写"，先问部署形态**：这个进程是单进程多线程，还是 gunicorn/uvicorn 多 worker？只要 CMD/启动配置里有 `--workers N (N>1)`，`threading.Lock` 就等于没锁。锁级别必须与**共享状态的边界**一致：共享文件→文件锁（flock/portalocker），共享 DB 行→行锁（本文件 D13 条目），共享进程内存→threading.Lock。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权三态与离线容器.md` 「哈希链履历的追加锁是 `threading.Lock`：prod 4 worker 并发追加 86% 撞 seq、整链被签发侧判 chain_broken」
