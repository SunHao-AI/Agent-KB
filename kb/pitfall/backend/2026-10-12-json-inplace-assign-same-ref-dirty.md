---
id: kb-20261012-8878
title: SQLAlchemy JSON 列 in-place 修改后 assign 同引用，dirty 判定不稳定
type: pitfall
domain:
- backend
tags:
- sqlalchemy
- json-column
- identity-map
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-07'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/Pydantic数据校验.md
---

# SQLAlchemy JSON 列 in-place 修改后 assign 同引用，dirty 判定不稳定

## 背景 / 现象

> 面向：`flysee-video-setting` 全部对 `Column(JSON)` 列做"修改后赋回"的 Service 代码（`algorithm.app_ids` / `algorithm_library.rule_ids` / `model.class_names` 等）。

**现象**：`update_library` 调 `_sync_library_rules` 想从 `algo.app_ids` 移除 `app_id`，`db.commit()` 后 `get_algorithm` 回读 `app_ids` 仍含旧值；`get_algorithm_detail` 用新 session 才看到真值。初步看起来是"commit 丢失"或"session 脏"，其实 SQLAlchemy 认为"值未变"跳过了 UPDATE。

## 根因

**根因**：旧代码

```python
app_ids = algo.app_ids or []
app_ids.remove(app_id)          # in-place 修改 list
algo.app_ids = app_ids          # 赋回——但仍是**同一个 list 对象引用**
```

`db.get(Algorithm, rule_id)` 期间该 Model instance 已在 `session.identity_map` 中，赋值路径 `__setattr__` 触发 `history = new_value - old_committed`；SQLAlchemy 对 JSON 列默认用 `==` 比较新旧值，`list.__eq__` 按元素比较 **新 list vs db-loaded 旧 list**——只要 `algorithms` 表有旧 instance 在身份地图，这个 `==` 比较命中的**同一个 object** 永远真，SQLAlchemy 跳过 UPDATE，commit 不落库。`db.refresh` 之后删除行读不到脏状态（因为 UPDATE 根本没发出去）。

## 解决方案

**解决**：**重建新 list 引用**，打破同一对象：

```python
app_ids = list(algo.app_ids or [])   # 浅拷贝 → 新对象
if app_id in app_ids:
    app_ids.remove(app_id)
    algo.app_ids = list(app_ids)     # double list → 强制 new 引用
```

或更省事：`algo.app_ids = [x for x in (algo.app_ids or []) if x != app_id]`。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/Pydantic数据校验.md` :: 「SQLAlchemy JSON 列 in-place 修改后 assign 同引用，dirty 判定不稳定」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

**预防**：
- **SQLAlchemy JSON 列的"映射"（append/remove/sort/replace 子项）必须在 assign 时 yielding 一个全新对象**：`list(...)` / `[...for]` / `{**d}` 均可。纯 in-place `+=` / `append` / `remove` 或局部修改后同引用赋回，SQLAlchemy 视为 no-op。
- **不要依赖 `db.refresh` 澄清赋值**：refresh 只是重新 SELECT 一次当前值，**不会把没发出去的 write 追发回库**——本 bug 正是因为误以为 commit/refersh 能兜底。
- 新 JSON 列迭代器先查身份地图：`db.expunge` 后重新 add 是最后手段，先改赋值方式。

## 参考

- 源记录: `docs/known-pitfalls/backend/Pydantic数据校验.md`
