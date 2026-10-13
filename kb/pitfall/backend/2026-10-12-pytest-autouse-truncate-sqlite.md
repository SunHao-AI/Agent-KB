---
id: kb-20261012-d661
title: 单测 SQLite 文件 + SQLAlchemy 自增表需 autouse 清表
type: pitfall
domain:
- backend
tags:
- pytest
- sqlite
- fixture
- test-isolation
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# 单测 SQLite 文件 + SQLAlchemy 自增表需 autouse 清表

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：M3 单测 `test_t14_refresh_expired` 中 `db.query(SysRefreshToken).first()` 返回的是上一条 t13 测试的旧行，导致行内 `row.expires_at = now-1s` 改错对象，断言 `DID NOT RAISE`。

## 根因

**根因**：pytest 中 `@pytest.fixture(autouse=True, scope="module")` 只拆文件，function-scoped fixture（如 `auth_engine`）默认不会自动清表，多测试共用同一 SQLite 文件累积残留数据。`query().first()` 是 ID 不确定回退点。

## 解决方案

**解决**：
- 选 `autouse=True` 的 function fixture，显式 `BEGIN ... DELETE FROM <table> ... COMMIT` 所有表，不依赖 test fixture 链
- 单测避免 `query().first()`，要么按条件查（`row.user_id == ctx.user_id AND revoked_at IS NULL`），要么先 DELETE 再查
- session-scoped 引擎（如 main db）用 `DELETE FROM` + cascade 顺序清理，而不是 `drop_all`/`create_all` 重走（开销大）

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->



## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
