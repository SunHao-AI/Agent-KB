---
id: kb-20261012-4bdf
title: perf 闸机 300~1000ms 地板的真根因是测试环境 SQLite fsync（非审计时序）：「挪出响应路径」被实验证伪，WAL+NORMAL
  才是根治
type: pitfall
domain:
- backend
tags:
- sqlite-wal
- fsync
- test-infra
- background-tasks
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-10-10'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# perf 闸机 300~1000ms 地板的真根因是测试环境 SQLite fsync（非审计时序）：「挪出响应路径」被实验证伪，WAL+NORMAL 才是根治

## 背景 / 现象

**日期**：2026-10-10（setting 仓；承接上一条目，同一定位链的第二轮实验闭环）

**背景**：上一条目把命中审计 GET 的 perf 预算放宽到 1500/3000ms 并注明"根治方向是把 write_oper 挪出响应路径"。本轮按该方向立项评估，**四项探针实验证伪了该方向**，并定位到真根因。

## 根因

**结论**：perf 闸机的 300~1000ms 是**测试环境 file-based SQLite 的 fsync 产物，非生产问题**（生产走 MySQL）。perf 采样是**闭环**的（每个样本必触发一次审计写），"挪出响应路径"只改变**谁在等**、不改变**总写量**，因此无法恢复闸机灵敏度，只会引入线程/队列/关闭丢弃策略复杂度与审计时序语义变化风险（实验 1/3 直接证实）。

## 解决方案

**方案（测试基建层，生产代码零改动）**：`tests/conftest.py` 对三个引擎挂 SQLAlchemy `connect` 事件，仅当 `dialect.name == "sqlite"` 时执行 `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL`；MySQL 分支天然 no-op。teardown 一并清理 `-wal` / `-shm` / `-journal` 附属文件（Windows 残留会锁主文件）。

## 验证

原文四项探针实测: TestClient 会等 BackgroundTask(113.7 vs 104.3ms); no-op write_oper 后 140.1→7.3ms; 后台线程持续写另一库时业务库读取 avg 飙到 7658.8ms; fsync 基准默认 139.6ms vs WAL+NORMAL 0.02ms; 治理后命中审计 GET 降到 5~8ms。

**探针实验（全部实测）**：
1. **TestClient 会等待 Starlette `BackgroundTask`**：`/health` 挂 100ms sleep，同步执行 113.7ms vs 挂 `resp.background` 104.3ms —— 一样等。即"用 BackgroundTasks 挪出响应路径"**在 TestClient 采样下不会降低任何测得耗时**。
2. **耗时归因**：`/v1/clients` 审计写开 avg=140.1ms，monkeypatch `AuditService.write_oper` 为 no-op 后 avg=7.3ms —— ~95% 耗时来自那一行同步 INSERT+COMMIT。
3. **挪到后台线程（队列+线程池）**：clients avg 仍有 126~134ms，几乎无改善，队列积压 0。
4. **进程级 I/O 串行化**：请求侧全 no-op 时读取 avg=8.6ms；后台线程持续写**另一个**库文件（test_auth.db）期间，业务库（test_flysee.db）读取 avg 飙到 **7658.8ms** —— 瓶颈不是双库文件锁争用，而是**本宿主/沙箱环境下 fsync 在全进程层面近乎串行化**。
5. **fsync 基准（决定性）**：file-based SQLite 单次 INSERT+COMMIT：默认（journal=delete + synchronous=FULL）**139.6ms**；`journal_mode=WAL + synchronous=NORMAL` **0.02ms**；`synchronous=OFF` 1.07ms；按"每写新建连接"（贴近 `_db()` 每次开 Session 的形态）复测：默认 110.4ms → WAL+NORMAL **0.60ms**。

**效果（实测）**：命中审计 GET 从 350~1000ms 降到 **5~8ms**（clients empty 8.2 / licenses 5.1 / with rows 7.6 / login 30ms），闸机预算从 1500/3000 收紧回 **200/400（login 300/600）**——恢复约 7 倍回归灵敏度，且不动生产代码、不改审计时序语义。

## 适用边界与反例

**要点**：
- **perf 异常先测"环境 I/O 地板"再怀疑代码路径**：一次 20 行的 sqlite3 基准（默认 vs WAL+NORMAL）30 秒就能定量排除/坐实 fsync 假设；本轮若先做基准，可省掉三个探针实验。
- **闭环采样的性能问题，"异步化"不降低总量只转移等待方**：只有当"等待方可并行化"（请求间无共享写介质）时，挪出响应路径才有效；本环境 fsync 近乎全进程串行（实验 4），挪到哪都要等。判定顺序：先问"总工作量能不能减"，再问"能不能并行"，最后才轮到"挪到哪"。
- **TestClient（httpx + anyio portal）会执行并等待 `Response.background`**：想用 BackgroundTasks/BackgroundMiddleware"骗过"测试客户端的计时是行不通的；同理 Starlette 的 lifespan/后台任务在 `with TestClient(app)` 退出前都会收尾。
- **PRAGMA 治理放 conftest 的 connect 事件而不是生产 database.py**：`synchronous=NORMAL` 在 WAL 下进程崩溃可能丢最近未 checkpoint 的事务——对测试库（每轮重建的临时文件）可接受，对生产必须保持默认 FULL。测试基建与生产的持久化语义要**有意分歧**，不要"顺手统一"。
- WAL 模式在 Windows 上会留下 `-wal`/`-shm` 附属文件，`Path.unlink` 主文件前先 dispose 引擎并连带清理附属文件，否则复跑时 WinError 32。
- 若将来 WAL 仍不达标，下一级旋钮是测试用 `:memory:` + StaticPool（彻底绕开 fsync），代价是跨连接可见性语义变化，需先审计所有直接开新连接的 fixture。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
