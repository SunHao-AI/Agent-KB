---
id: kb-20261012-b360
title: ModelSchema 缺 model_id 字段：Pydantic 静默丢弃导致"绑定模型"保存即丢
type: pitfall
domain:
- backend
tags:
- pydantic
- extra-ignore
- silent-data-loss
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-07'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/Pydantic数据校验.md
---

# ModelSchema 缺 model_id 字段：Pydantic 静默丢弃导致"绑定模型"保存即丢

## 背景 / 现象

> 面向：`flysee-video-setting` 算法表单绑定模型链路（`AlgorithmForm.vue` → `POST/PUT /v1/algorithm/algorithms` → `algorithm.models` JSON 列 → 查看弹窗/导出）。

**现象**：新增算法时选择"绑定模型"（如 #24），保存成功；再次"查看"该算法，模型配置里"绑定/路径"一栏为空白。DB 实据：`models.first_model` 只有 `weight_path: ""`，`model_id` 键根本不存在。

## 根因

**根因**：前端 `onBindModel` 把 `model_id` 写进表单并随 payload 提交，但后端 `ModelSchema` 未声明 `model_id` 字段。Pydantic 默认 `extra='ignore'`，校验后 `data.model_dump()` 已不含该键 → service 原样落库 → 查看弹窗 `model.model_id` 为 undefined、`weight_path` 为空串（空串不走 `displayVal` 的 null 兜底），渲染出空单元格。更严重的连带影响：`export_service._build_models_snapshot` 靠 `model_id` 定位权重文件，该规则导出必然失败。前端校验 `(!weight_path && !model_id)` 恰好放行，全程无任何报错——**静默丢数据**。

## 解决方案

**解决**：
1. `ModelSchema` 显式声明 `model_id: Optional[int] = None`，`weight_path` 改为默认 `""`（绑定态允许为空）。
2. 消费端把存在性判断改为真值判断：`_build_models_snapshot` 的 `if "model_id" in m:` → `if m.get("model_id"):`（字段补齐后**未绑定**规则也会以 `model_id: null` 入库，`in` 判断会误入新格式分支以 `id=None` 查库报错）；`rules_models_backfill._compute_version_hash` 同步改 `isinstance(raw.get("model_id"), int)`。
3. 已损坏历史记录无法恢复 `model_id`，需在表单重新选择绑定模型再保存。

## 验证

回归测试 `tests/test_api_algorithm.py::test_create_algorithm_persists_bound_model_id`（原文「预防」段指认的 POST/PUT → GET 回读断言）。

## 适用边界与反例

**预防**：
- **前端表单字段必须能 grep 到后端 Schema 同名声明**。前端提交、后端不声明 = 静默丢弃，比 422 更隐蔽。新增表单字段后补一条"POST/PUT → GET 回读断言字段值"的回归测试（见 `tests/test_api_algorithm.py::test_create_algorithm_persists_bound_model_id`）。
- 可选字段以 `null` 入库后，所有下游消费端的 `"key" in obj` 存在性判断都要重审一遍，改真值/类型判断。

## 参考

- 源记录: `docs/known-pitfalls/backend/Pydantic数据校验.md`
