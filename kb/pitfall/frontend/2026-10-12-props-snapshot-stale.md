---
id: kb-20261012-5642
title: 派生 snapshot 只读 vs 用户输入双写：`props` 建 snapshot 表不会随 emit 回写更新（Vue `<script setup>`）
type: pitfall
domain:
- frontend
tags:
- props
- snapshot
- reactivity
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-07'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表单交互与数据绑定.md
---

# 派生 snapshot 只读 vs 用户输入双写：`props` 建 snapshot 表不会随 emit 回写更新（Vue `<script setup>`）

## 背景 / 现象

> 面向：`flysee-video-setting` 前端所有 `buildRows`/`buildOptions`/`buildXxSnapshot` 等**内部以 `props` 数组构造本地 ref 副本**的复合组件（`ModelClassTable.vue` 的 `rows`、`AlgorithmForm.vue` 的 `mapEnums`、`ClassLabelsEditor` 等）。

`ModelClassTable.vue` 早期实现用 `props.classNames` 构造 `rows = ref([])`（snapshot），在有 `ModelClassTable` + 顶部"英文名拼接" el-input 的双写场景下做多选 on-change 回写 `form.models.first_model.EN_name`。UI 顶部输入栏是**只读渲染** `props.classNames[?].en`；点选后 emit 事件把 `EN_name` 写回 `props.form.models.first_model.EN_name`（父组件 store），但**表格 rows 里的 `row.en`/`row.ch` 字符串是首次 mount 时的模板字符串，不随 `model.EN_name` 变**。用户看到 UI 显示的还是旧英文名（如 `main_road`），实际 `form.models.first_model.EN_name` 已经是新值（`main_road2`）——auto-apply 尝试的视觉症状 "规则侧 main_road 未同步"。

## 根因

Vue `<script setup>` 里 `props.classNames` 是**只读 snapshot**；组件内 `buildRows()` 拆行时 `rows.value = (props.classNames || []).map(c => ({ en: c.en, ch: c.ch, checked: ... }))` 拿到的是**字符串字面量拷贝**（非引用），后续 `model.EN_name` / `props.form.models.xx.EN_name` 被父组件改写时，**这些字符串字面量不会联动**（数组元素是 primitive 而非 ref 化的对象）。即便子组件在 auto apply 时 emit 新值回父 store，父 store 的更新只回滚到 `props` 上（`props.classNames` 重新赋值），子组件的 `rows` 数组里**已经存下的字符串字面量**依然停留在 mount 时的值——因为 `buildRows` **只在 `watch(props.classNames, ...)` 里重跑**，而 `props.classNames` 重新赋值在多数场景下触发不了（父组件不重建数组引用，只改 `props.form.models.first_model.EN_name` 这个 store 字段）。

## 解决方案

（3 条原则，`ModelClassTable.vue` 属于原则 1 场景）：
1. **若子组件的展示仅源于 props，不要内部 auto apply 用 emit 写回，也不要试图通过内部 ref 驱动 UI**：所有文案渲染走 `props`（props 更新时 Vue 驱动 DOM 更新），**不 introducing 一份本地 snapshot 存字符串**。`ModelClassTable.vue` 纯 hint 化就是走这条路——row 数据每次都由 `props.classNames` 重算；emitSelection 用户手动勾选触发，写回 form 后下次 `props.classNames` 重新赋值时 watch 触发 → buildRows 重建。
2. **若必须"临时 ref + 提交时刷回 form"**（如 `AlgorithmForm.vue` 的 `radius/composite/cluster` temp ref 场景），**emit 前统一 syncAllToForm**，让临时 ref 是唯一事实源；snapshot 只用于**渲染**，不作为 emit 来源。
3. **若父组件重新生成 `props.classNames` 引用**（调 `/v1/models/{id}` 重新拉），watch 才能感知——**"父组件改同引用内字段"场景下不做 snapshot**，消除"snapshot 落后于 store" 的分支。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

（grep mat）：
- 新建 `buildRows`/`buildX*` 类 snapshot 时，凡 emit 后依赖 snapshot 更新展示 → **要么让父组件重新生成 props 引用，要么子组件自己按最新值重算**（如在 `emitSelection` 后调 `buildRows()`，但这会引入 snapshot 已 emit old-values 又 rebuild 的时序坑，最好仍走原则 1 的纯 props 路由）。
- 代码评审时**grep 子组件内 `row.en`、`r.checked` 等 snapshot 字段赋值来源**：来源于 `props.*.map(c => ...)` 的字符串字面量 ≠ parent store，别把 emit 误认为能回滚 snapshot。
- 类似风险点：`views/index` 首页菜单 `filteredMenus` computed 是**派生**（非 snapshot），可以引用同一引用更新 —— 但 `views/algorithms/index.vue` 的 `visibleAlgos` 早期用 `ref` snapshot，`watchEffect` 里拉 API 才刷新，有此坑 — 派生优于 snapshot。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单交互与数据绑定.md`
