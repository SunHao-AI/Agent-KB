---
id: kb-20261012-e65c
title: exclude_unset=True 递归剔除嵌套模型未显式字段
type: pitfall
domain:
- backend
tags:
- pydantic
- exclude-unset
- nested-model
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

# exclude_unset=True 递归剔除嵌套模型未显式字段

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：上传带类别标签后，GET 回显的类别对象缺 `threshold`/`color`/`bg_alpha` 键，前端/测试断言失败；`PUT /classes` 路径正常。

## 根因

**根因**：`model_dump(exclude_unset=True)` 对嵌套 `ClassNameItem` 同样生效——未显式设置的字段被递归剔除，缺键数组原样入库、原样回显。PUT 用 `model_dump()`（完整字段）故正常，暴露上传路径问题。

## 解决方案

**解决**：`init_upload` 中 `validate_class_names` 之后对 `class_names` 每项 `setdefault` 补全 `threshold/color/bg_alpha` 为 None（只补缺、不覆盖显式值）。**exclude_unset 只解决顶层字段缺省问题，嵌套模型字段需显式补全**。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/Pydantic数据校验.md` :: 「exclude_unset=True 递归剔除嵌套模型未显式字段」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例





源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/Pydantic数据校验.md` :: 「exclude_unset=True 递归剔除嵌套模型未显式字段」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

