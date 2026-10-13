---
id: kb-20261012-7882
title: Windows CI/本地跑 pytest 并发写同一 SQLite 文件触发 WinError 32 文件锁
type: pitfall
domain:
- backend
tags:
- pytest
- windows
- sqlite
- file-lock
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# Windows CI/本地跑 pytest 并发写同一 SQLite 文件触发 WinError 32 文件锁

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`tests/test_auth_provider.py` 与 conftest.py 的 session `clean_tables` 在 Windows 上**同时单测跑**时，20 个 T01–T20 全部 `PermissionError: [WinError 32] 文件被另一个进程占用`。单跑 OK，组合跑炸。

## 根因

**根因**：两个 fixture 都持有 `sqlite:///./test_auth.db` 文件句柄（一个 module-scope `auth_env` 在测试前/后 `unlink`，另一个 function-scope `clean_tables` 在测试中频繁重连 + dispose）。Windows 上**未 close 的句柄不允许 `unlink`** —— Linux/Mac 上 unlink 只是把目录项摘掉（in-use 进程继续写 inode），Windows 上不允许。

## 解决方案

**解决**：让 `test_auth_provider.py` 用独立文件 `test_auth_private.db`，彻底切断两个 fixture 的文件竞争。这是 Windows 共享 SQLite 多 fixture 的**唯一干净解**。（替代方案：单测改用 `:memory:`，但 SQLAlchemy 整体生命周期管理太复杂。）

## 验证

原文对照实验(实测): 组合跑时 T01-T20 全部 `PermissionError: [WinError 32]`, 单跑 OK 组合跑炸; 改用独立文件 `test_auth_private.db` 后「彻底切断两个 fixture 的文件竞争」。

## 适用边界与反例

**预防**：新增 M3 类「独立建自己的 SQLite」单测时，**恒定约定**用独立文件名（加 `_private` 后缀），**绝不复用** conftest 的 session 文件。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
