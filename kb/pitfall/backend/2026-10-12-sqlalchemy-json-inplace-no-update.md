---
id: kb-20261012-77fa
title: SQLAlchemy JSON 列原地修改不触发更新
type: pitfall
domain:
- backend
tags:
- sqlalchemy
- json-column
- orm
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/ORM与数据.md
---

# SQLAlchemy JSON 列原地修改不触发更新

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`switch_model_version` 更新规则 `algorithm.models` JSON 中的 `model_id` 后，`db.commit()` 成功但数据库实际未变更（规则仍引用旧版本）。

## 根因

**根因**：`models` 是原生 `JSON` 列（未启用 `MutableDict`）。直接 `m["model_id"] = x` 修改 dict 内部后，再浅拷贝外层 dict 赋回 `algo.models`，新旧值按 `==` 比较仍相等（内层 dict 是同一对象、已被原地改掉），SQLAlchemy 认为无变更，不生成 UPDATE。

## 解决方案

**解决**：修改 JSON 列时重建对象——遍历原结构，对每个要改的嵌套项用 `{**m, "model_id": 新值}` 生成新 dict，拼出全新的外层 dict 再整体赋回 `algo.models = new_models`，保证新旧值不相等。**凡是 SQLAlchemy JSON 列的嵌套修改，都必须重建被修改对象链，不能原地改**。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例



## 参考

- 源记录: `docs/known-pitfalls/backend/ORM与数据.md`
