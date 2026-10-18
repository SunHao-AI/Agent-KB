---
id: kb-20261012-57cd
title: SQLAlchemy + SQLite 主键自增：必须纯 INTEGER，跨方言场景需 DDL 端处理
type: pitfall
domain:
- backend
tags:
- sqlalchemy
- sqlite
- bigint
- ddl
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/ORM与数据.md
---

# SQLAlchemy + SQLite 主键自增：必须纯 INTEGER，跨方言场景需 DDL 端处理

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`fs_uav_auth` 10 张表的 SQLAlchemy 2.0 ORM 单次 INSERT 在 SQLite 单测中报 `sqlite3.IntegrityError: NOT NULL constraint failed: sys_user.id`。生产 DDL（`01-auth-schema.sql`）正确声明 `BIGINT(20) UNSIGNED AUTO_INCREMENT`，但 ORM 模型用 `BigInteger` 时 SQLite 拒绝自增。

## 根因

**根因**：SQLite 只在 `INTEGER PRIMARY KEY`（int 类型无宽度修饰）且同时是表主键时启用隐式 rowid alias 自动编号。SQLAlchemy 渲染 `BigInteger` 为 SQL 关键字 `BIGINT`（不是 SQLite 意义上的 INTEGER 别名），因此 `id BIGINT NOT NULL AUTOINCREMENT` 链路缺失 rowid alias。同时 `BigInteger().with_variant(Integer, "sqlite")` 在 SQLAlchemy 2.0 下 DDL 渲染仍按 base type 输出 `BIGINT`，variant 不生效。

**事实修正（2026-09-18，借鉴点 C `license_renew_requests` 落地时复验）**：上文"`with_variant(Integer, "sqlite")` 在 SQLAlchemy 2.0 下 DDL 渲染仍按 base type 输出 `BIGINT`，variant 不生效"**已不成立**（当次结论疑为未编译验证的推断）。实测本仓当前 SQLAlchemy 版本：

```
id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)

SQLITE>>  id INTEGER NOT NULL,                      # rowid alias，自增可用
MYSQL >>  id BIGINT NOT NULL AUTO_INCREMENT,        # 生产列宽不变
```

复验命令（无需连库）：`CreateTable(Model.__table__).compile(dialect=sqlite.dialect())`。

因此**跨方言表的推荐写法就是 `with_variant`**（本仓既有先例 `backend/models/export_release.py`），既能保住 MySQL `BIGINT AUTO_INCREMENT`，又能让 SQLite 单测自增；裸 `BigInteger` 主键才会在 SQLite 报 `NOT NULL constraint failed: <table>.id`。本文首段"统一声明 `Integer`"仅在**纯测试用表**（生产 DDL 另有手写文件）时适用，不要套用到 `01-schema.sql` 已声明的业务表上。

## 解决方案

**解决**：
- 测试/开发用 SQLite 主键统一声明 `Integer` 而非 `BigInteger`（`_BigInt = Integer`）
- 生产库的列宽/BIGINT 由独立 DDL（`docker/init/auth/01-auth-schema.sql`）保证，与 ORM 模型解耦；ORM 模型承担"主键标度语义"而非 DDL 渲染责任
- 不依赖 ORM `create_all` 生成生产 DDL；DDL 必须手写并通过 `docs/migrations/` 文档迁移

## 验证

复验命令（无需连库）：`CreateTable(Model.__table__).compile(dialect=sqlite.dialect())`，实测输出见下方「事实修正」段（SQLITE>> id INTEGER NOT NULL / MYSQL>> id BIGINT NOT NULL AUTO_INCREMENT）。

## 适用边界与反例

**笔记**：以后若真的需要按 ORM 模型渲染 DDL（Alembic autogenerate），用 `with_variant` 时要编译 `CreateTable` 验证方言输出，不要相信"variant 名存在就等于生效"。

**踩坑触发点**：`Base.metadata.create_all` 只在表不存在时建表，旧 `test_flysee.db` 残留旧 Schema 时改 ORM 不生效——改主键定义后必须删库重跑（或换文件型库名），否则会误判为"改了没用"。

## 参考

- 源记录: `docs/known-pitfalls/backend/ORM与数据.md`
