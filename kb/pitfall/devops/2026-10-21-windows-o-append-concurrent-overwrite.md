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
- multiprocess
- os-file-lock
- msvcrt-locking
- fcntl
- sidecar
- 多进程
- 跨进程锁
- 文件锁
- 追加写
- auto-reviewed
scope: stack
status: accepted
confidence: verified
created: '2026-10-21'
updated: '2026-11-11'
severity: high
related:
- kb-20261013-4d62
source:
  project: TencentDB-Agent-Memory
revision:
  reason: content-edited
  from_status: accepted
  at: '2026-11-11'
review_by: '2027-11-11'
verified_by: agent
verification:
  evidence: '2026-11-11 本机Windows实测: traces/2026-11-06/07/11 各1条孤儿片段实锤跨进程写竞态; 补 sidecar
    OS 锁(svcrt LK_NBLCK)后 scripts/loadtest.py --only D2 8进程x150事件落盘1200/1200 丢行0碎行0重复0;
    pytest 424 passed(唯一失败 test_run_replays_line_completed_after_partial 为既有节流抖动,
    隔离重跑通过); kb lint exit0 + index --check 无漂移'
  reviewed_at: '2026-11-11'
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

多进程场景在此之上再套一层 OS 文件锁，见下方"新发现（2026-11-11）"。

## 验证

`scripts/ab-bench.py --against HEAD`（base=HEAD worktree 检出，与改动交替轮次，消除本机 7× 噪声）：

| 变体 | 16线程×2000 事件 | 碎行 | 单线程 p50 |
| --- | --- | --- | --- |
| 基线 HEAD | 丢行 699~1566（35%~78%） | 11~38 | ≈1.0~1.4ms |
| 修复后 | 落盘 2000/2000 事件（文件 2001 行含 meta 首行） | 0 | ≈0.9~1.7ms |

修复已固化为门禁：`python scripts/loadtest.py`（D 场景丢行/碎行/重复任一非零即退 1）。
全量回归 268 passed。

## 适用边界与反例

- **同进程多线程**由 `_APPEND_LOCK` 串行；**多进程**同写当日文件线程锁跨不过进程，
  Windows 上同机制照样互相覆盖。2026-10-21 当时判断"实际概率低（跨仓各写各的
  traces/）"故未上 OS 锁——2026-11-11 被线上证伪（见"新发现"），已补 sidecar 文件锁。
- Linux/macOS 上 `O_APPEND` 内核原子追加，同代码不丢行——但**跨平台项目不可依赖**此行为。
- 行完整性前提是"一次 write 写完一行"：把一行拆成两次 write，即使在 Linux 上也会被其他
  写者插入而碎行。
- 与数据库层的丢失更新（见 related 的 JSON 整列读-改-写条目）是不同层问题：那是事务/行锁
  语义，这是 OS 文件句柄语义，修复手段不可互相套用。

## 新发现（2026-11-11）：多进程同写真实发生，已补 OS 级跨进程文件锁

**线上证据**：`traces/2026-11-06.jsonl`、`2026-11-07.jsonl`、`2026-11-11.jsonl` 各残留
1 条**孤儿片段**（文件尾部半行、头部字节已永久丢失，如 `osed"]}` / `"注入旧名"]}`），
serve 启动扫描报 `bad line 跳过`，且 2026-10-21 修复后仍在产生——能留下碎行的只剩
**跨进程**写（serve 的 ingest 线程与另一进程的 `kb search` 埋点同刻追加当日文件），
当日各进程各写各仓的侥幸假设被证伪。附带发现：个别旧账本头部有连续 CRLF 段（曾被
工具以文本模式整段重写，`git text=auto` 归一化掩盖了提交差异）——清理坏行须按字节
只剔坏行、其余原样保留，勿整文件文本重写。

**修复**（`src/kb/trace.py::_append_locked`）：线程锁内再取 OS 级独占文件锁，双保险：

```python
# Windows: msvcrt.locking(fd, LK_NBLCK, 1)；POSIX: fcntl.flock(fd, LOCK_EX | LOCK_NB)
# 非阻塞轮询 + 3s 超时；超时静默丢该条事件——埋点永不阻塞检索链路
with _APPEND_LOCK:                        # 同进程多线程(原有)
    取 sidecar OS 独占锁                   # 跨进程(新增)
    单句柄一次写完 meta 首行 + 事件行
```

要点：(a) 锁对象是 **sidecar**（`traces/YYYY-MM-DD.lock`），不直接锁数据文件——避免与
追加句柄互相干扰；(b) sidecar 后缀**不能带 `.jsonl`**：读侧（serve/spider-live/trace
自身）全靠 `glob("*.jsonl")` 收集账本，带上就污染解析；(c) `traces/*.lock` 入
`.gitignore`；(d) meta 首行存在性判断保持在双锁内，与前述要点 (a) 同理。

**验证**：`scripts/loadtest.py --only D2`（新增多进程门禁：8 个独立 python 进程 ×
150 事件同时追加当日文件）→ 落盘 1200/1200、丢行 0、碎行 0、重复 0（2026-11-11 本机
Windows）；D 线程场景与全量 pytest 同步通过。

## 参考

- 修复与测试: `src/kb/trace.py`（`_APPEND_LOCK` + `_append_locked` 双锁）、
  `scripts/loadtest.py` D / D2 场景、`scripts/ab-bench.py`
- MSVC `_open` 文档: `_O_APPEND` "read/write position is set to end of file"（open 时定位）
- related: kb-20261013-4d62（数据库层丢失更新，机制不同勿混用修法）
