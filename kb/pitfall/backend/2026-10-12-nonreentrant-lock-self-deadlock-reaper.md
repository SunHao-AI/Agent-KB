---
id: kb-20261012-f351
title: '非重入 REGISTRY_LOCK 持锁自死锁: reaper 循环体内二次加锁 → 引擎"活着但永不再启动任务"(py-spy 旁挂抓栈定位)'
type: pitfall
domain:
- backend
tags:
- multiprocessing-lock
- deadlock
- py-spy
- two-phase-lock
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-24'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# 非重入 REGISTRY_LOCK 持锁自死锁: reaper 循环体内二次加锁 → 引擎"活着但永不再启动任务"(py-spy 旁挂抓栈定位)

## 背景 / 现象

**日期**: 2026-09-23 (engine 仓 `app/services/detect_service.py`)

**现象**: 创建任务后前端「视频流接入中…」数分钟仍不出画(真凶实为**永久**卡死, 直到引擎重启才恢复)。引擎容器 `healthy`、日志零 ERROR、`/status` 免锁读路径正常——但所有新任务永卡 `pending`, start/stop 全部无效。"活着但拒绝工作"是此类锁死锁的标志性表象, 健康检查全绿完全掩盖问题。

## 根因

**根因**: `REGISTRY_LOCK = _MP.Lock()`(spawn context, **非重入**)。`_process_reaper` 在 `with self.REGISTRY_LOCK:` 持锁遍历 registry, 循环体内调用 `_release_model_cleanup(key)`, 而该函数内部**再次 acquire 同一把锁** → 同线程二次加锁永久阻塞 → 锁被 reaper 线程永久持有 → 后续所有需要该锁的线程(start/stop/status/force_stop)全部卡死在 `multiprocessing/synchronize.py:95 __enter__`。触发链: reaper 到点回收超时任务(1800s) → 自死锁 → 之后创建的新任务永久 pending。**同一把坑共三处**: `stop()`(历史已修, 代码注释有记录)、`_force_stop_task`(本次修)、`_process_reaper`(历史修复时**漏修**)。

## 解决方案

**解决**(两段式锁模式): 锁内只做**快照/判定/登记**, 一切回收动作(kill 进程树 / DB 回写 / SSE / gpu release / release_model)挪到锁外:

```python
# _process_reaper: 锁内只做快照, 回收动作全部挪到锁外(见 _reap_one 死锁说明)
with self.REGISTRY_LOCK:
    snapshot = list(self.PROCESS_REGISTRY.items())
for key, info in snapshot:
    try:
        self._reap_one(key, info, now, max_run)  # ⚠ 绝对禁止持锁调用
    except Exception as e:  # 单条目回收失败不得中断巡检线程
        logger.error(f"[REAPER] 条目回收异常 key={key}: {type(e).__name__}: {e}")
```

`_force_stop_task` 同款改造: 锁内仅存在性判定 + 冷却窗口登记, 出锁后再做 update_status / SSE / kill / release / cleanup。回归单测 `tests/test_reaper_deadlock.py` 用**看门狗**模式锁死: 回收逻辑放 daemon 线程, `t.join(timeout=5)` 后 `assert not t.is_alive(), "reap 未完成 → REGISTRY_LOCK 嵌套自死锁复发"`; 关键在 `_release_model_cleanup` **走真实实现**(它才是第二次 acquire 点), 只 mock 外围副作用(update_status/sse/kill/gpu release)。

## 验证

原文定位法(实测): 旁挂调试容器 `--pid=container` + SYS_PTRACE 跑 `py-spy dump --pid 1`, 三个业务线程栈顶全部停在 `synchronize.py:95 __enter__`; 回归单测 `tests/test_reaper_deadlock.py` 看门狗模式锁死。

## 适用边界与反例

**定位法**(容器内无 ptrace 权限):
```bash
# 引擎容器内 pip 装 py-spy 直接 dump 会 Permission denied (os error 13)
# → 旁挂调试容器共享 PID namespace + 注入 SYS_PTRACE:
docker run --rm --pid=container:flysee-video-algorithm-engine --cap-add SYS_PTRACE `
  python:3.10-slim sh -c "pip install py-spy -q && py-spy dump --pid 1"
# ⚠ 勿加 --native: CUDA 进程 native 符号化会永久挂起
```
三个业务线程(_consume / _process_reaper / _license_reaper_loop)栈顶全部停在 `synchronize.py:95 __enter__` → 锁泄漏实锤; reaper 栈多一帧 `_release_model_cleanup` 直接指认二次加锁点。

**通用教训**:
- **非重入锁(multiprocessing.Lock / spawn context) + 持锁调用私有辅助函数是高危模式**: 辅助函数(或其后续演化)内部再拿同锁即自死锁, 且死锁发生在"回收/兜底"路径上, 平时无感知, 一到超时回收/异常兜底才引爆。规范: 持锁段内只允许纯数据结构操作, 函数调用一律视为雷区。
- **修一处死锁必须全量 grep 该锁的调用点**: 同一把锁的嵌套坑本仓共三处, 历史只修了报出问题的 `stop()`, reaper/force_stop 漏修——后续线上引爆。修复动作 = `grep -n "REGISTRY_LOCK"` 后逐处检查调用链是否回调自身。
- **"无日志"≠"卡在那段代码"**: engine 日志停在 `[START]` 行曾误导怀疑模型解密/文件损坏, 实际模型加载根本还没轮到(卡在拿锁)。进程外部观测(抓栈)优于日志断点猜测; `py-spy dump` 旁挂容器是无侵入取证首选。
- **健康检查要覆盖"业务活性"**: `/health` 200 + 容器 healthy 不代表调度锁没死; 长期方案可给 status/start 路径改 `lock.acquire(timeout=n)`, 拿不到锁即 ERROR 级告警。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
