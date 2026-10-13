---
id: kb-20261012-0d17
title: 联调 smoke 脚本「API 落库成功、脚本却查不到」：InnoDB REPEATABLE READ 快照（2026-09-18）
type: pitfall
domain:
- backend
tags:
- mysql
- repeatable-read
- session-scope
- smoke-script
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-18'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# 联调 smoke 脚本「API 落库成功、脚本却查不到」：InnoDB REPEATABLE READ 快照（2026-09-18）

## 背景 / 现象

> 面向：容器内跑的端到端烟测脚本（`docker exec -w /app <backend> python /tmp/xx.py`）——脚本既发 HTTP 调 API、又直接用 `SessionLocal()` 查库做断言时。

**现象**：签名 POST 返回 200 且 `duplicated:false`（明确已落库），紧随其后的同脚本查库却是空列表；`pending_total=0`；用查到的 `rid`（实为 `None`）再调业务方法抛 `ValueError: 续期申请不存在`。同时伴生 `SAWarning: fully NULL primary key identity cannot load any object`。

## 根因

**根因**：MySQL InnoDB 默认 **REPEATABLE READ**。脚本第一次 `db.query(...).scalar()` 就开启了一个长事务并固定了读视图快照；此后 API 在**另一个 Session** 里 `INSERT + COMMIT`，本 Session 仍读旧快照 → 永远看不到新行。**这是脚本缺陷，不是产品缺陷**（换个进程/新连接立刻能看到）。`SAWarning` 是 `db.get(Model, None)` 的副产物：`rid=None` 来自上一步查空。

## 解决方案

**解决**：
1. **每次读取都新开 `SessionLocal()`（用完即 close）**，不要在脚本开头建一个长生命周期 Session 贯穿始终；或读前 `db.commit()` / `db.expire_all()` 结束快照事务。
2. **断言要基于「新会话读到的真实主键」**，不要复用 API 响应里的字段（本项目精简视图按设计不含 `id`）。
3. **清理语句别用可能为 `None` 的 id**：`filter(Model.id == rid).delete()` 在 `rid=None` 时生成 `WHERE id = NULL`，**匹配 0 行且静默成功**（SQL 三值逻辑），残留数据会污染下一轮 smoke。清理前先断言 `rid is not None`，或用 `id.in_(ids)` 且 `ids` 非空时才执行。

## 验证

原文实录: POST 返回 200 且 `duplicated:false` 而同脚本查库为空、伴生 `SAWarning: fully NULL primary key identity cannot load any object`; 「换个进程/新连接立刻能看到」为对照实锤(脚本缺陷而非产品缺陷)。

## 适用边界与反例

**防踩**：脚本里凡「先写后读」的断言，都要问一句"我这个 Session 的事务是什么时候开的"。同一现象在 SQLite（默认 autocommit/无 MVCC 快照）上不复现，所以本地单测全绿也不代表联调脚本没这毛病。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
