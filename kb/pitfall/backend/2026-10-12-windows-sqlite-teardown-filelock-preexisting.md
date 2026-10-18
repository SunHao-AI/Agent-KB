---
id: kb-20261012-22c1
title: 横切：测试层的 Windows 文件锁（预存问题，未修复）
type: pitfall
domain:
- backend
tags:
- pytest
- windows
- sqlite
- preexisting
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-06'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/2026-09-06-audit-gets-and-pwd-initial.md
---

# 横切：测试层的 Windows 文件锁（预存问题，未修复）

## 背景 / 现象

`tests/test_task_b_01_audit.py::test_no_user_not_audited` 与 `tests/test_task_b_02_pwd_initial.py::test_reset_pwd_no_body_with_env_accepts` 在 teardown 阶段报：

```
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process, 'D:\\Workplace\\flysee-video-setting\\test_flysee.db'
```

## 根因

原因：session-scoped autouse fixture `database` 末尾 `DB_FILE.unlink()` 时，SQLite 连接仍在空闲连接池里占着文件句柄，**Windows** 不允许在用文件上 unlink；Linux 永远不会报这个问题。**不影响测试执行结果**（8/8 与 16/16 都 PASS），只是 teardown 阶段红一条。

## 解决方案

**建议（不在本次范围）**：

- 短期：在 `pytest.ini` 的 `filterwarnings` 里忽略 `PermissionError`
- 长期：fixture teardown 加 `engine.dispose()` 后再 `unlink`，并用 `unlink(missing_ok=True)` 兜底

（已在 `README.md` 索引中的「Windows 跑 pytest 并发写同一 SQLite 文件触发文件锁」条目列过，仍未完全落地。）

## 验证

原文实录: teardown 报 `PermissionError: [WinError 32] ... test_flysee.db`, 但**不影响测试执行结果**（8/8 与 16/16 都 PASS），只是 teardown 阶段红一条; Linux 永远不会报这个问题。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/2026-09-06-audit-gets-and-pwd-initial.md` :: 「横切：测试层的 Windows 文件锁（预存问题，未修复）」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/backend/2026-09-06-audit-gets-and-pwd-initial.md`
