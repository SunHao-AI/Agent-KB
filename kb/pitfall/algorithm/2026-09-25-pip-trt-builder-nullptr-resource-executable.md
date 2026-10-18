---
id: kb-20261013-772d
title: 'pip 版 TRT 容器内 `trt.Builder()` 构造 nullptr: builder_resource 声明 executable stack
  被 seccomp 拒绝'
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-25'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: medium
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/TRT引擎校验与冷启动预热.md
---

# pip 版 TRT 容器内 `trt.Builder()` 构造 nullptr: builder_resource 声明 executable stack 被 seccomp 拒绝

## 背景 / 现象

**连带坑**：`docker exec` 新进程**不继承 PID 1 的 `LD_LIBRARY_PATH`**（TRT/cublas/
cudnn8 路径在 ENV 里只对主进程生效是假象——实际 exec 起来是空）, `import tensorrt`
直接 `libcudnn.so.8: cannot open shared object`。脚本内按 PID 1 的
`/proc/1/environ` 同款路径自动补。权威路径值与完整构建流程见
`docs/trt-engine-cross-gpu-runbook.md`。

## 根因

pip wheel 里的 `libnvinfer_builder_resource.so` ELF 程序头 `PT_GNU_STACK`

带 `PF_X`(可执行栈), 容器默认 seccomp 拒绝 `READ_IMPLIES_EXEC` 类 mprotect → dlopen

失败。只有 **builder**(构建 engine)路径加载此库, 推理 runtime 只 dlopen

`libnvinfer.so`, 所以"能推理、不能构建"。

**解决**（`scripts/build_trt_engine.py::_patch_builder_resource_stack_flag` 已自动化）：

就地清该库 PT_GNU_STACK 的 PF_X 位（先备份 `*.orig` 保幂等）。**LD_PRELOAD 打补丁的

副本实测无效**——libnvinfer 内部按 soname 从原路径 dlopen, 不认 LD_PRELOAD 顶替。

推理链路不加载此库, 对运行容器零影响。

## 解决方案

源记录未单列解决方案, 见「背景 / 现象」与参考段原文。

## 验证

LD_PRELOAD 指向副本实测无效——libnvinfer 内部按 soname 从原路径 dlopen，不认 LD_PRELOAD 顶替；推理链路不加载此库，对运行容器零影响。

## 适用边界

本条来自 flysee_video_algorithm 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/engine/TRT引擎校验与冷启动预热.md` 「pip 版 TRT 容器内 `trt.Builder()` 构造 nullptr: builder_resource 声明 executable stack 被 seccomp 拒绝」
