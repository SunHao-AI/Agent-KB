---
id: kb-20261012-4949
title: 迁移脚本幂等性与执行顺序
type: pitfall
domain:
- database
tags:
- mysql
- migration
- ddl
scope: universal
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/约束与迁移.md
---

# 迁移脚本幂等性与执行顺序

## 背景 / 现象

迁移脚本(`ALTER TABLE ADD COLUMN ...; UPDATE 回填; ALTER TABLE ADD UNIQUE KEY`)重复执行会在 ADD COLUMN 处失败(列已存在)。

## 根因

一次性迁移脚本未加 `IF NOT EXISTS` 保护, 且未考虑重复执行。

## 解决方案

迁移脚本按"先加列(带默认值保证存量行可回填)→ 回填 → 后加唯一约束"的顺序执行(先回填再加约束可避免默认值撞约束); 重复执行会失败, 属预期, 执行前备份目标表(`mysqldump <db> <table>`)。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/database/约束与迁移.md` :: 「迁移脚本幂等性与执行顺序」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

适用于存量库的一次性 DDL 迁移脚本; 全新初始化库走 `docker/init/01-schema.sql` 路径, 不依赖本流程(见 schema-sql-orm-sync 条目)。DDL 执行须按项目规范由用户确认后手动完成。

## 参考

- 源记录: `docs/known-pitfalls/database/约束与迁移.md` (git 首次收录 2026-09-01)
