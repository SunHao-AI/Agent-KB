---
id: kb-20261013-f051
title: '`dict.get(k, default)` 防不住"键存在但值为 `""`"：空展示名原样带出为落库空标签'
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-11'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/类别映射与结果落库.md
---

# `dict.get(k, default)` 防不住"键存在但值为 `""`"：空展示名原样带出为落库空标签

## 背景 / 现象

- **"空串"是有语义的值，别在有语义的边界上依赖默认值回落**：映射表存"用户留空的展示名"时，
  要么入口归一（首选，单点收敛），要么每个消费点 `or` 回落；绝不允许"键存在值为空"穿过整条链路到落库。
- **跨 layer 的映射（raw name → 展示名 → 目标名）在唯一出口归一**：web→引擎的唯一适配出口归一，
  比在引擎各处打补丁收敛；引擎侧兜底只是纵深防御的一层。

## 根因

web 规则页 UI 语义是 `{{ cls.class_name_output || cls.class_name }}`——

空展示名回落原类名，即"空串"的语义是"未填展示名"，**不是**一个有效标签值；输入框允许留空。

但引擎侧两处映射都用 `dict.get(k, default)`：

```python

# Detector.__init__（旧）

self.class_name_map[class_name] = c.get("class_name_output", class_name)

# tools.build_rule_class_map（旧）

mapping[cls] = c.get("class_name_output", cls)

```

`dict.get(k, default)` **只在键缺失时**回落；键存在但值为 `""` 时原样返回空串。

随后消费侧 `class_name_map.get(original_label, original_label)` 同样因键存在而拿到 `""`，

空标签一路带进 `clusters_to_objects` → 落库。

## 解决方案

```python

# app/engine/yolov/inference.py  Detector.__init__

class_name_output = c.get("class_name_output") or class_name

self.class_name_map[class_name] = class_name_output

# app/core/tools.py  build_rule_class_map

out = c.get("class_name_output") or cls

mapping[cls] = out

# app/core/tools.py  clusters_to_objects

final_label = class_name_map.get(original_label) or original_label

```

web 侧在唯一出口 `_engine_rule_classes` 做源头归一（空展示名补 `class_name or class_id`），

引擎侧 `or` 只做历史/异构上报的兼容兜底。回归测试锁定空串回落语义：

`tests/test_class_name_empty_fallback.py`。

## 验证

回归测试锁定空串回落语义：`tests/test_class_name_empty_fallback.py`。

## 适用边界

`aivis_images` **只由 AI 直播实例落图**（合成 task_id = `{task_id}-live-{rule_id}`，

经 `POST /v1/tasks/{task_id}/live/{rule_id}` 启动）；主任务 `POST /v1/tasks/{task_id}/start`

**不写 `aivis_images`**。要复现 objects 落库必须启动 live 实例，否则查不到图片行会误判"没跑起来"。

- **`dict.get(k, default)` 只在"键缺失"时回落，防不住"键存在但值为 `""`"**。凡字段语义是

  "未填则回落"（可选展示名/别名/标题），赋值与取值两侧都必须用 `x.get(k) or default`。

## 参考

- 源记录: `docs/known-pitfalls/engine/类别映射与结果落库.md` 「`dict.get(k, default)` 防不住"键存在但值为 `""`"：空展示名原样带出为落库空标签」
