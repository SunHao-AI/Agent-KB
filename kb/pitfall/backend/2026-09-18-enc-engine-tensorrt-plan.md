---
id: kb-20261013-2a56
title: 模型 `.enc` 解出来的 `.engine` 是 TensorRT plan，运行时版本必须与构建版本匹配
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-18'
updated: '2026-10-13'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/任务派发与算法联动.md
---

# 模型 `.enc` 解出来的 `.engine` 是 TensorRT plan，运行时版本必须与构建版本匹配

## 背景 / 现象

解密 OK、GPU 分配 OK，`YOLO(load_path)` 加载解密出的 `*.engine` 时抛 `ModuleNotFoundError: No module named 'tensorrt'`；补装新版 TensorRT 后改抛 `Failed due to an old deserialization call on a newer plan file`。

## 根因

三重错位叠加。① 模型 `.enc` 是加密包，后缀兜底 `.engine`，

而生产 GPU 镜像 venv 里**根本没装 tensorrt**（`pyproject.toml` 只有 `ultralytics`）；

② 该 plan 由 **TensorRT 8.6.0.12** 构建（plan 头版本字节 `08 06 00 0C`，引擎内含 sm_75 cubin），

TensorRT 只保证**同大版本内** plan 兼容，TRT 10.x 反序列化 8.6 的 plan 被官方拒绝；

③ `.engine` 还锁 GPU 计算架构，跨 sm 架构（如 sm_75 ↔ sm_86）同样不可用。

结论：**TensorRT engine 是"构建期产物"，不是可移植的模型资产**。

## 解决方案

二选一——(a) 部署运行时（算法 GPU 镜像）**内置与资产一致的 TRT 版本**，

并用相同 GPU 架构机器构建；(b) **模型侧改交可移植资产**（`.pt` 或 `.onnx`），

由算法服务在目标机用当前 ultralytics/TRT 现场构建引擎（推荐，避免锁死老 runtime）。

已实测：`python:3.10-slim` + TRT 8.6 wheel + cu11 运行库，在 GTX 1660 Ti(sm_75) 上对该 8.6 plan

`deserialize_cuda_engine` **成功**并完成 GPU 推理（`execute_v2` 出特征图），

证明资产本身没坏，纯粹是运行时版本错位；而生产 GPU 镜像（CUDA 12 + TRT 10.13）反序列化同一 plan 失败。

纯 pip 搭建 TRT 8.6 运行时的配方（绕开 apt 卡源）：

`pip install tensorrt-8.6.0-cp310 wheel`（自动带 cu12 依赖）

+ `pip install --no-deps nvidia-cublas-cu11 nvidia-cuda-runtime-cu11`（TRT 8.6 是 CUDA 11 构建，

要 `libcublas.so.11`/`libcudart.so.11`，cu11 wheel 的 so.11 与已有 so.12 同目录共存即可）

+ `nvidia-cudnn-cu12==8.9.7.29`（提供 `libcudnn.so.8`，注意大版本 8 不是 9）

+ 运行前 `LD_LIBRARY_PATH` 加入 `site-packages/nvidia/*/lib`。

## 验证

已实测：`python:3.10-slim` + TRT 8.6 wheel + cu11 运行库，在 GTX 1660 Ti(sm_75) 上对该 8.6 plan `deserialize_cuda_engine` **成功**并完成 GPU 推理（`execute_v2` 出特征图），证明资产本身没坏，纯粹是运行时版本错位；而生产 GPU 镜像（CUDA 12 + TRT 10.13）反序列化同一 plan 失败。

## 适用边界

`model_cache` 入库/打包阶段应校验并记录 `trt_version` + `compute_cap`，

与部署环境做兼容性前置校验（不匹配则拒绝启用并给出明确文案），

而不是把不兼容的资产派发到推理子进程深处再炸。

另外，TensorRT plan 的版本可用如下方式离线读出（无需安装对应 runtime）：

```python

import struct

raw = open(engine_path, "rb").read()

meta_len = struct.unpack("<I", raw[:4])[0]   # ultralytics 头部：4 字节 LE 长度 + JSON 元数据

plan = raw[4 + meta_len:]

assert plan[:4] == b"ftrt"

print(plan[4:10].hex())   # plan 版本区，例如 080600 0c => TRT 8.6.0.12

```

## 参考

- 源记录: `docs/known-pitfalls/backend/任务派发与算法联动.md` 「模型 `.enc` 解出来的 `.engine` 是 TensorRT plan，运行时版本必须与构建版本匹配」
