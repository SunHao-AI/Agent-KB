---
id: kb-20261012-60c8
title: 唯一约束对软删除行生效，应用层检查必须一致
type: pitfall
domain:
- database
tags:
- mysql
- unique-constraint
- soft-delete
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/约束与迁移.md
---

# 唯一约束对软删除行生效，应用层检查必须一致

## 背景 / 现象

`models` 表新增唯一约束 `uk_models_name_version (model_name, version_major, version_minor, version_patch)` 后, 删除模型再重传同名模型报 500(应用层校验通过但 INSERT 撞约束)。

## 根因

`is_del` 是软删除标记(行保留), 唯一约束对软删除行同样生效; 应用层查询若过滤 `is_del=False`, 会认为版本号"空着", 与 DB 约束语义冲突。

## 解决方案

设计唯一约束时同步明确软删除行的语义——版本号作为历史档案不应复用, 应用层唯一性检查不过滤 `is_del`; 自动递增用循环跳过已占用号; 入库 commit 兜底捕获 `IntegrityError` 防并发竞态。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/database/约束与迁移.md` :: 「唯一约束对软删除行生效，应用层检查必须一致」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

若业务语义要求"删除后版本号可复用", 则唯一约束应包含 `is_del`(或改用删除时间戳参与联合唯一), 而非放宽应用层检查——两种语义必须二选一并保持 DB 与应用层一致。

## 参考

- 源记录: `docs/known-pitfalls/database/约束与迁移.md` (git 首次收录 2026-09-01)
