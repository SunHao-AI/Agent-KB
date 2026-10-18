---
id: kb-20261012-367c
title: 自定义组件未声明 disabled prop 导致"只读"失效
type: pitfall
domain:
- frontend
tags:
- props
- disabled
- v-model
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表单交互与数据绑定.md
---

# 自定义组件未声明 disabled prop 导致"只读"失效

## 背景 / 现象

版本更新模式下给 `ColorPicker`/`ClassLabelsEditor` 传 `:disabled="isVersionUpdate"`，但界面仍可交互，且修改会经 v-model 写回表单并随上传提交（继承数据可被篡改）。

## 根因

子组件未声明 `disabled` prop，传入值作为 fallthrough attribute 落到根元素 `<div>` 上无效（div 无 disabled 语义）；且 v-model 链路完好，用户修改会正常写回。

## 解决方案

子组件显式声明 `disabled` prop 并落实到内部控件（按钮/输入禁用）+ 所有 emit 路径加 `if (props.disabled) return` 守卫。给自定义组件传原生 HTML 属性前，先确认该组件是否声明了对应 prop。

## 验证

（自本条方案段提取）只读模式下组件内按钮/输入全部禁用；尝试交互后检查表单数据未被改写（emit 守卫生效，修改不随上传提交）。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单交互与数据绑定.md`
