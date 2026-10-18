---
id: kb-20261012-28ff
title: 批量 UPDATE 与 INSERT 同表需注意 autoflush 顺序
type: pitfall
domain:
- backend
tags:
- sqlalchemy
- autoflush
- orm
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/ORM与数据.md
---

# 批量 UPDATE 与 INSERT 同表需注意 autoflush 顺序

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`complete_upload` 想让新上传的版本成为当前版本（`is_current=True`），先 `db.add(model)` 再对同模型执行 `UPDATE ... SET is_current=False`，结果新插入的行 `is_current` 也被清成 False。

## 根因

**根因**：SQLAlchemy 执行查询（含 `Query.update()`）前会 autoflush 把 pending 对象先 INSERT 落库，随后批量 UPDATE 命中所有同 `model_name` 行（含刚插入的新行），把新行标记一并清掉。

## 解决方案

**解决**：先执行批量 UPDATE 清除旧标记，再 `db.add()` 新行（新行天然带目标标记）。**凡"插入新行 + 批量更新同表其他行"的场景，批量 UPDATE 必须放在 add 之前，利用 autoflush 时机避免新行被连带更新**。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/ORM与数据.md` :: 「批量 UPDATE 与 INSERT 同表需注意 autoflush 顺序」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例





源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/ORM与数据.md` :: 「批量 UPDATE 与 INSERT 同表需注意 autoflush 顺序」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

