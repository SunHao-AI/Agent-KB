---
id: kb-20261012-5704
title: 01-schema.sql 必须与 ORM 模型同步演进，否则全新初始化的库缺列
type: pitfall
domain:
- database
tags:
- mysql
- docker
- schema-sync
- orm
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/约束与迁移.md
---

# 01-schema.sql 必须与 ORM 模型同步演进，否则全新初始化的库缺列

## 背景 / 现象

重置数据卷全新初始化后, backend 启动正常但接口 500, 日志报 `OperationalError 1054: Unknown column 'algorithm.color' in 'field list'`(连同 `bg_alpha`)。

## 根因

ORM 模型(`Algorithm.color/bg_alpha`)新增了列, 但只更新了 `docker/init/migrations/` 下的迁移脚本, 未同步回 `docker/init/01-schema.sql` 的 CREATE TABLE。而 entrypoint 只在首次建卷时执行顶层 init SQL、忽略 migrations 子目录, 导致全新初始化出的表天然缺列——存量库靠人工迁移修好了, 全新库反而坏。

## 解决方案

- 给 ORM 加/改列时, 必须同步更新 `01-schema.sql` 对应表的列定义(保持幂等 CREATE TABLE 完整反映最新结构); 一次性迁移脚本仅用于存量库;
- 存量库修复 DDL 需按项目规范由用户确认后执行:

```sql
ALTER TABLE algorithm ADD COLUMN color VARCHAR(50) DEFAULT '#0EA0F6FF' ..., ADD COLUMN bg_alpha FLOAT DEFAULT 1.0 ...
```

## 验证

排查手段: 比对 ORM 模型类与 SHOW COLUMNS 输出, 逐表核对; 本次其余表(models/clients/export_releases 等)均已一致, 仅 algorithm 缺 color/bg_alpha。

## 适用边界与反例

一次性迁移脚本仅用于存量库; 全新初始化路径只认顶层 `01-schema.sql`(entrypoint 忽略子目录, 详见 initdb-runs-only-on-first-volume 条目)。

## 参考

- 源记录: `docs/known-pitfalls/database/约束与迁移.md` (git 首次收录 2026-09-01)
