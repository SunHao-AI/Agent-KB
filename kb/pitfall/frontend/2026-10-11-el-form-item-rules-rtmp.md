---
id: kb-20261013-e006
title: el-form-item 局部 :rules 与表单级 rules 是「合并」不是「覆盖」→ 文件直喂上传完点开启任务必报"输入流地址需为 rtmp://…
  开头"
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-10-11'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/表单校验与ElementPlus.md
---

# el-form-item 局部 :rules 与表单级 rules 是「合并」不是「覆盖」→ 文件直喂上传完点开启任务必报"输入流地址需为 rtmp://… 开头"

## 背景 / 现象

「创建分析任务 → 本地视频文件 → 文件直喂」流程，视频上传完成后点「开启任务」，表单红字报"输入流地址需为 rtmp:// / rtsp:// / http(s):// 开头的完整地址"，任务无法创建。

## 根因

1. 上传 form-item 挂着 `prop="input"` + 局部 `:rules="[{required '请先上传视频文件'}]"`（复用 input 必填语义）；

2. 表单级 `rules.input` 另挂了 `validateStreamUrl` 协议白名单校验（2026-09-28 为**实时流手输地址**前置的格式校验）；

3. **Element Plus 对同一 field 的校验规则 = 表单级 rules[prop] ∪ form-item 局部 rules（合并）**，局部声明不会顶掉表单级。上传完成 `form.input` 变成 `file://<upload_id>/<filename>` 时触发 `change`，合并进来的协议校验对 `file://` 判失败 → 错误常驻并在 submit `validate()` 时拦截。

文件直喂的 `file://` 是系统自己生成的合法输入，天然不在"手输流地址"协议白名单里——两条规则服务的场景不同却作用到了同一 field。

## 解决方案

`rules` 改为按模式计算的 `computed`：`isFileMode` 时 `input`/`output` 给 `[]`（自动生成的合法值不做手输协议校验，必填由上传 form-item 局部 required + `submitBlockReason` 双重把关）；实时流模式保留协议白名单 + 同地址回环拦截。

## 验证

机制实证：上传完成 `form.input` 变成 `file://<upload_id>/<filename>` 时触发 `change`，合并进来的协议校验对 `file://` 判失败 → 错误常驻并在 submit `validate()` 时拦截。修复后实时流模式保留协议白名单 + 同地址回环拦截。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单校验与ElementPlus.md` 「el-form-item 局部 :rules 与表单级 rules 是「合并」不是「覆盖」→ 文件直喂上传完点开启任务必报"输入流地址需为 rtmp://… 开头"」
