---
id: kb-20261012-3ece
title: Pydantic model_dump() 默认注入导致 setdefault 继承失效
type: pitfall
domain:
- backend
tags:
- pydantic
- model-dump
- inheritance
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/Pydantic数据校验.md
---

# Pydantic model_dump() 默认注入导致 setdefault 继承失效

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：版本更新（parent_model_name）时父模型元数据未被继承，新版本静默落库为默认值（如类别为空、阈值 0.5），无任何报错。

## 根因

**根因**：`init_upload` 收到的是 `data.model_dump()`——Pydantic 总是输出全部字段（含默认值：model_type=["detect"]、class_names=None、input_size=640 等），key 永不缺失，service 层 `data.setdefault(k, parent.xxx)` 全部为 no-op。

## 解决方案

**解决**：API 层改为 `data.model_dump(exclude_unset=True)`，只保留请求显式提供的字段，setdefault 继承才生效。配套核查：`init_upload`/`complete_upload` 中所有 `data.get(...)`/`meta.get(...)` 都要有安全默认值（description/uploaded_by/input_size 等），缺省行为不能破坏。**凡"未显式提供时取默认/继承"的逻辑，都要注意 Pydantic model_dump() 会注入默认值这一行为**。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/Pydantic数据校验.md` :: 「Pydantic model_dump() 默认注入导致 setdefault 继承失效」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例





源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/Pydantic数据校验.md` :: 「Pydantic model_dump() 默认注入导致 setdefault 继承失效」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

