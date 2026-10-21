---
id: kb-20261021-6223
title: 多线程以 append 模式并发写同一文件互相覆盖（Windows O_APPEND 仅 open 时定位 EOF）：观测埋点事件最高丢 78% 并产生半行碎片
type: pitfall
domain:
- devops
tags:
- windows
- o-append
- jsonl
- thread-safety
- trace
- auto-reviewed
scope: stack
status: accepted
confidence: verified
created: '2026-10-21'
updated: '2026-10-21'
severity: high
related:
- kb-20261013-4d62
verified_by: agent
verification:
  evidence: 'scripts/ab-bench.py --against HEAD 交替轮次复现: 基线16线程x2000事件丢行699~1566(35%~78%)+碎行11~38,
    修复后落盘2001/2001碎行0; 单线程p50两版均约1ms无回退; scripts/loadtest.py D场景门禁通过; pytest 全量268
    passed(2026-10-21 本机Windows实测)'
  reviewed_at: '2026-10-21'
source:
  project: TencentDB-Agent-Memory
---

# 多线程以 append 模式并发写同一文件互相覆盖（Windows O_APPEND 仅 open 时定位 EOF）：观测埋点事件最高丢 78% 并产生半行碎片

## 背景 / 现象

Agent-KB 观测服务 `kb serve` 的 `/api/ingest` 由 `ThreadingHTTPServer` 多线程处理，每个请求经
`kb/trace.py::append_event` 向当日 `traces/YYYY-MM-DD.jsonl` 追加一行 JSON。压测
（16 线程 × 125 事件并发写同一文件）在 Windows 上稳定复现：

- 2000 个事件只落盘 416~1662 行（**丢行率 17%~78%**，多轮波动）；
- 文件中出现 11~38 条**不可解析的碎行**（两条 JSON 的字节互相穿插/覆盖）；
- 全程无任何 OSError——写"成功"了，数据就是没了。

单线程顺序写完全正常，因此日常 `kb search` 埋点从不暴露此问题；只有并发消费方（ingest、
批量回放灌数）会触发。

## 根因

Windows CRT 的 `O_APPEND` 只在 **open 时**把文件指针定位到当时 EOF，之后每个句柄按**自己的**
指针推进写入，写入期间不重新定位。两个线程（或进程）同时 open 同一文件时指针相同，
后写者的字节直接**覆盖**先写者刚写的内容；文件长度只推进到各句柄写到的最远位置，
落在重叠区的数据永久丢失。两个句柄指针交错推进的位置差还会留下**空洞/半行**，即碎行。

POSIX 的 `O_APPEND` 由内核在**每次 write 时**原子地定位到 EOF，因此 Linux/macOS 上同一代码
通常只是行间交错（行内字节完整），不丢数据——这是"Windows 上炸、CI(Linux) 上绿"的典型形态。

## 解决方案

进程内互斥 + 锁内单句柄一次写完（`kb/trace.py`）：

```python
_APPEND_LOCK = threading.Lock()  # 同进程多线程 append 互斥

with _APPEND_LOCK:
    head = [] if f.exists() else [meta_line]   # meta 首行检查也必须在锁内
    with f.open("a", encoding="utf-8") as fh:
        fh.write("".join(ln + "\n" for ln in [*head, line]))
```

要点：(a) `f.exists()` 判断必须在锁内，否则并发下重复写 meta 首行；(b) 一个句柄一次
`write` 写完整行，不拆多次 write。耗时代价：16 线程强竞争下总耗时约 2.3×（997ms→2292ms）；
真实常态（单线程/各进程各写各文件）无可测差异（p50 均 ≈1ms，交替 A/B 交错在噪声内）。

## 验证

`scripts/ab-bench.py --against HEAD`（base=HEAD worktree 检出，与改动交替轮次，消除本机 7× 噪声）：

| 变体 | 16线程×2000 事件 | 碎行 | 单线程 p50 |
| --- | --- | --- | --- |
| 基线 HEAD | 丢行 699~1566（35%~78%） | 11~38 | ≈1.0~1.4ms |
| 修复后 | 落盘 2000/2000 事件（文件 2001 行含 meta 首行） | 0 | ≈0.9~1.7ms |

修复已固化为门禁：`python scripts/loadtest.py`（D 场景丢行/碎行/重复任一非零即退 1）。
全量回归 268 passed。

## 适用边界与反例

- **本修复只覆盖同进程多线程**（ThreadingHTTPServer 场景）。Windows 上**多进程**同时追加同一
  日文件（serve ingest 与另一 CLI 进程同刻写同仓）仍可能丢行，需 OS 级文件锁
  （`msvcrt.locking` / portalocker）；实际概率低（跨仓各写各的 traces/），暂未上。
- Linux/macOS 上 `O_APPEND` 内核原子追加，同代码不丢行——但**跨平台项目不可依赖**此行为。
- 行完整性前提是"一次 write 写完一行"：把一行拆成两次 write，即使在 Linux 上也会被其他
  写者插入而碎行。
- 与数据库层的丢失更新（见 related 的 JSON 整列读-改-写条目）是不同层问题：那是事务/行锁
  语义，这是 OS 文件句柄语义，修复手段不可互相套用。

## 参考

- 修复与测试: `src/kb/trace.py`（`_APPEND_LOCK`）、`scripts/loadtest.py` D 场景、
  `scripts/ab-bench.py`
- MSVC `_open` 文档: `_O_APPEND` "read/write position is set to end of file"（open 时定位）
- related: kb-20261013-4d62（数据库层丢失更新，机制不同勿混用修法）
