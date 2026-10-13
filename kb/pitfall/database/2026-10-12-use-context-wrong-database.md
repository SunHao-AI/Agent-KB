---
id: kb-20261012-e16b
title: 从 migration 合入 01-schema.sql 时表落错库（多库文件 USE 上下文错位）
type: pitfall
domain:
- database
tags:
- mysql
- schema-sync
- multi-database
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/约束与迁移.md
---

# 从 migration 合入 01-schema.sql 时表落错库（多库文件 USE 上下文错位）

## 背景 / 现象

migration 路径(已建库升级)一切正常, 但走 `01-schema.sql` 全新初始化的库, 服务读 `license_state`/`license_audit`/`client_license_event` 报 1146 表不存在; 服务层 `except` 把异常吞成"退化为模型级授权", 故障进一步被掩盖。测试环境 `conftest.py` 把业务库与管理库指向同一个 SQLite 文件, 测试全绿完全暴露不出该问题。

## 根因

把 `migrations/2026-09-03-*.sql`(表名带 `fs_uav_area_mark.` 显式前缀)合入 `01-schema.sql` 时, 误把建表语句追加到了 `USE fs_uav_admin` 块之后。`01-schema.sql` 是多库顺序脚本, 同一段 DDL 不带库名前缀时落在最近一次 `USE` 的库, 位置放错块 = 落错库。

## 解决方案

- 该三张表整体移入 `USE fs_uav_area_mark` 块内(`models` 表之后、`USE fs_uav_admin` 之前), DDL 与 migration 文件逐字一致;
- 沉淀规则: 向多库 `01-schema.sql` 合入新表时, 先 `grep -n "^USE "` 确认插入点处于哪个库上下文; migration 文件用库名前缀、schema 文件靠 USE 块位置, 两种风格混用时最易错位;
- 排查手段: `SELECT table_schema, table_name FROM information_schema.tables WHERE table_name IN (...)` 一条 SQL 即可核对表实际落库。

## 验证

修复后全量重放验证幂等:

```powershell
Get-Content 01-schema.sql -Raw -Encoding UTF8 | docker exec -i <mysql> mysql -uroot -p<pwd>
```

exit 0。

## 适用边界与反例

适用于不带库名前缀的多库顺序 init 脚本; 双库 `fs_uav_area_mark`(业务) + `fs_uav_admin`(管理)。注意 conftest 单 SQLite 文件的测试设置无法暴露落错库问题, 测试全绿不等于多库初始化正确。

## 参考

- 源记录: `docs/known-pitfalls/database/约束与迁移.md` (条目对应变更 2026-09-04)
