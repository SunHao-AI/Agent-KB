---
id: kb-20261013-353f
title: 自定义上传块的必填错误「上传成功后不消失」：程序性赋值不触发 EP change 校验，须状态翻转处显式 clearValidate
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-11'
updated: '2026-10-13'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/表单校验与ElementPlus.md
---

# 自定义上传块的必填错误「上传成功后不消失」：程序性赋值不触发 EP change 校验，须状态翻转处显式 clearValidate

## 背景 / 现象

文件直喂模式，若先点过一次「开启任务」（触发全表单校验出"请先上传视频文件"红字），之后上传成功、按钮已可用，红字却**永远挂在表单上**——"一切就绪但红字还在"的矛盾显示。

## 根因

el-form-item 校验的 `change` 触发依赖**内部 EP 输入控件的 modelValue 变化事件**。该 form-item 的内容是自定义上传块（拖拽区/进度条/成功态），没有 el-input/el-select；`form.input` 由 `syncFileUrls` 直接赋值，不经过任何控件 → EP 收不到 change → 首次校验产出的错误没有任何时机被重验清除。（上一轮修协议白名单时浏览器实测里 `formErrs:["请先上传视频文件"]` 已现此残留，当时被"能提交"掩盖未识别。）

## 解决方案

给该 form-item 挂 `ref="videoFieldRef"`，在语义翻转点显式清除：

```js

watch(uploaded, (val) => {

  if (val) nextTick(() => videoFieldRef.value?.clearValidate())

})

```

只清该项（`videoFieldRef` 而非 `formRef`），其它字段校验不受影响。

## 验证

上一轮修协议白名单时浏览器实测里 `formErrs:["请先上传视频文件"]` 已现此残留，当时被"能提交"掩盖未识别——程序性赋值不触发 EP change 校验，须状态翻转处显式 clearValidate。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单校验与ElementPlus.md` 「自定义上传块的必填错误「上传成功后不消失」：程序性赋值不触发 EP change 校验，须状态翻转处显式 clearValidate」
