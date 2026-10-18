---
id: kb-20261012-2d04
title: 对同一文件的多处编辑必须串行执行并逐一核对
type: pitfall
domain:
- frontend
tags:
- editing
- agent-workflow
- lost-update
scope: universal
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 对同一文件的多处编辑必须串行执行并逐一核对

## 背景 / 现象

对同一 .vue 文件的两处模板块并行发起两次替换编辑，两处均返回成功，但事后读取发现只有后写入的一处生效，先完成的主模型块改动被覆盖丢失（lost update）。

## 根因

两次编辑各自基于同一份文件快照计算与写回，后一次写入整体覆盖了前一次的结果；工具返回"成功"只代表替换动作执行了，不代表最终文件同时包含全部改动。

## 解决方案

同一文件的多处修改严格串行执行，每处改完立即重读核对再进行下一处；批量修改完成后用特征标识符（如新组件名、新增函数名）全局检索，逐条确认所有预期改动都在位。构建通过不能替代此核对——被丢失的改动若不影响语法仍可能编译成功。

## 验证

（自本条方案段提取）批量修改完成后用特征标识符（新组件名、新增函数名）全局检索逐条确认在位；注意构建通过不能替代此核对——被丢失的改动若不影响语法仍可能编译成功。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
