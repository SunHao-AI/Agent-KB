---
id: kb-20261013-074a
title: '现场构建默认 FP16 优先导致精度敏感模型漏检: build_precision 三档可选（auto/fp32/fp16）'
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-25'
updated: '2026-10-13'
severity: high
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/TRT引擎校验与冷启动预热.md
---

# 现场构建默认 FP16 优先导致精度敏感模型漏检: build_precision 三档可选（auto/fp32/fp16）

## 背景 / 现象

**症状**（2026-09-25 真实 FEISHI_MODEL yolo11n 车辆模型端到端实测）：轨道 2 现场构建
TRT 日志报 `72 weights subnormal FP16`, 同一帧原 `.pt` 检出 5 个 car、FP16 engine
只检出 2 个——小目标置信度在 FP16 下跌破阈值, **漏检只在现场暴露, 打包侧完全看不出来**。
**处置**（spec `docs/superpowers/specs/2026-09-25-build-precision-design.md`）：
`model_cache.build_precision`（auto/fp32/fp16）逐模型可配, web 模型管理对话框改,
下次任务启动生效——**运维必须能在客户现场本地改, 而不是等重新打包**。fp32=只建 FP32
（模型原精度）; fp16=构建失败降 FP32 时产物头标 `downgraded_from=fp16`（日志+产物头
双留痕, 排障时一眼看出"想要 FP16 但建不出来"）。fp8/int8 硬件门槛（TRT>=9.1+Ada /
校准流程）, 现网 TRT 8.6+Turing 一律 422。
**缓存键连带坑**：cache_key 精度维度从 bool 改字符串（fp16/fp32）后, 存量引擎缓存
一次性全 miss（键变了）——**属预期的一次性重建, 不是 bug**; 若沿用 bool 语义
（`'fp32' if not fp16`）则显式 fp32 设置会误命中历史 FP16 降级产物, 精度改了不生效。
**subnormal 判定线索**：TRT builder WARNING 里的 `subnormal FP16` 计数即风险指标——
非零就说明该网络有权重低于 FP16 正规数下限（~6e-5）, 对小目标/低置信度场景应默认
建议 fp32。

## 根因

FP16 的正规数下限（约 6e-5）装不下某些网络的小权重：builder 报 `subnormal FP16` 即有权重下溢，小目标置信度在 FP16 下跌破检测阈值造成漏检；打包侧不做现场场景回放，这类精度损失只在现场暴露。因此精度必须现场逐模型可配，且 cache_key 精度维度要参与键计算（字符串 fp16/fp32）——沿用 bool 语义会让显式 fp32 误命中历史 FP16 降级产物，改了不生效。

## 解决方案

源记录未单列解决方案, 见「背景 / 现象」与参考段原文。

## 验证

2026-09-25 真实 FEISHI_MODEL yolo11n 车辆模型端到端实测：轨道 2 现场构建 TRT 日志报 `72 weights subnormal FP16`，同一帧原 `.pt` 检出 5 个 car、FP16 engine 只检出 2 个——小目标置信度在 FP16 下跌破阈值，漏检只在现场暴露，打包侧完全看不出来。

## 适用边界

本条来自 flysee_video_algorithm 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/engine/TRT引擎校验与冷启动预热.md` 「现场构建默认 FP16 优先导致精度敏感模型漏检: build_precision 三档可选（auto/fp32/fp16）」
