---
id: kb-20261012-08b8
title: MySQL 数据卷为旧 Schema 时，新增建表语句不会自动补建
type: pitfall
domain:
- database
tags:
- mysql
- docker
- initdb
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
related:
- kb-20261012-795e
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/约束与迁移.md
---

# MySQL 数据卷为旧 Schema 时，新增建表语句不会自动补建

## 背景 / 现象

backend 启动报 `RuntimeError: 缺少数据表: ['clients']`, 库中只有早期建的 `algorithm`/`algorithm_library`/`customers`, 而 `docker/init/01-schema.sql` 中明明已有 `clients` 建表语句。

## 根因

mysql 容器把 `docker/init/` 挂载到 `/docker-entrypoint-initdb.d`, 但该目录下的脚本只在数据卷首次初始化时执行; 数据卷已存在时(即使 `docker compose restart` 或重新 up)不会重跑, 后加入 schema 的表永远不会自动创建。另外 entrypoint 会忽略子目录(日志出现 `ignoring /docker-entrypoint-initdb.d/migrations`), `docker/init/migrations/*.sql` 在全新初始化时同样不会执行。

## 解决方案

- 本地开发可接受清空数据时:

```powershell
docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml -f docker/docker-compose.dev.yml down -v
```

重置卷后重新 `dev.ps1 start`, 让 init 脚本全量重跑;

- 需保留存量数据时: 由用户手动执行缺失表的 DDL(从 01-schema.sql 摘取对应 CREATE TABLE);
- 新表定义必须直接合入 `01-schema.sql`(幂等 `CREATE TABLE IF NOT EXISTS`), 不要依赖 `migrations/` 子目录做全新初始化。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

附带坑: 全新卷冷启动时 MySQL 初始化耗时可达 2 分钟以上, compose 健康检查可能先超时报 `container mysql is unhealthy`, 见 mysql-healthcheck-start-period 条目。`down -v` 会清空数据, 仅限可丢弃数据的本地开发环境。

## 参考

- 源记录: `docs/known-pitfalls/database/约束与迁移.md` (git 首次收录 2026-09-01)
