---
id: kb-20261012-c4c6
title: 整表锁定用 `el-form :disabled` 级联：el-button 也吃级联、el-upload 不吃、显式 :disabled prop
  会盖过级联
type: pitfall
domain:
- frontend
tags:
- element-plus
- disabled
- form-lock
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-25'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表单交互与数据绑定.md
---

# 整表锁定用 `el-form :disabled` 级联：el-button 也吃级联、el-upload 不吃、显式 :disabled prop 会盖过级联

## 背景 / 现象

> 面向：任务创建成功后左栏整张表单置灰锁定（web `views/tasks/create.vue` formLocked），EP 2.13.1。

任务创建成功后表单参数已固化为该任务快照，继续编辑全是无效操作。逐控件加 `:disabled="formLocked"` 要改十几处且后续新增控件必漏（同"锁修一处漏两处"教训），正确做法是 `<el-form :disabled="formLocked">` 单点级联。

## 根因

- **吃级联**（`useFormDisabled()` 读 form context）：input / input-number / select（含 multiple tag 删除按钮）/ radio-group / checkbox / switch / **el-button**（`button/src/use-button.mjs` L23 `const _disabled = useFormDisabled()`）。折叠面板 el-collapse 非输入控件不受影响, 锁定态仍可展开查看参数。
- **不吃级联**：`el-upload`（源码只认自己的 `disabled` prop）→ 必须手工 `:disabled="uploadBusy || formLocked"`。
- **显式 prop 盖过级联**：已有 `:disabled="uploadBusy"` 的按钮/组件，显式 prop 优先级高于 form context → 锁定态照样可点，必须改为 `uploadBusy || formLocked` 手工并入。

## 解决方案

- `formLocked = computed(() => !!createdTaskId.value)` 单一状态源；解锁仅靠「再建一个」`resetForNewTask()` 清 `createdTaskId`（failed/stopped 不自动解锁——那是任务真实快照，改参数重试走再建一个）。
- 锁标识：标题行 `v-if="formLocked"` 的 el-tag（Lock 图标 + tooltip「如需修改请点再建一个」），样式 `.card-title__lock { flex: none }` 紧跟标题，不与 `margin-left:auto` 的 action 按钮抢位。
- 复制按钮随级联灰掉可接受（地址在右栏任务摘要仍可见）——级联方案的默认行为优先于逐个保活的冲动。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

- 整表禁用/只读一律 `el-form :disabled`，禁止逐控件铺 `:disabled`。
- 用级联前先 **grep 表单内不消费 form context 的组件**（upload、自定义组件、原生 input）与**已有显式 :disabled 的控件**，这两类是级联盲区，逐个手工并入锁定条件。
- "锁定后仍可保留的操作"（复制/展开查看）要先确认其控件是否吃级联，再决定保活成本是否值得。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单交互与数据绑定.md`
