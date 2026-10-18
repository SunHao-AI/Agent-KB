---
id: kb-20261012-c823
title: 多个文件并行 SearchReplace 同样出现丢写
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

# 多个文件并行 SearchReplace 同样出现丢写

## 背景 / 现象

同时（同一轮 tool call）对 4 个独立文件（customers.py/algorithm.py/exports.py/models.py 等）发起各自的 import 与函数签名替换，每文件都返回"成功"，逐一 grep 全量核对发现：algorithm.py 接口签名都对了但 import 丢失；models.py、exports.py 整文件 import 与签名均未落盘；仅 customer.py 部分生效。

## 根因

并非 SearchReplace 工具本身的写冲突（不同文件间其实可以并行——一个文件多次 SearchReplace 在同一轮消息里串行下发是 ORM 原子写），更可能是**单轮 assistant 消息内一次性发出>8 个 SearchReplace call 时**，调度器对工具的批量入队处理出现 race——日志回显的 diff 与实际写盘不严格一致；后写的文件可能污染共享的写缓存。

## 解决方案

1. **单轮消息内同一文件多次 SearchReplace 避免 > 5 个；跨文件并行也建议 ≤4 个**，不要一次性下发 8+ 个修改
2. **每文件改完都 Read 回读一次**（特别是被多手法触发多次编辑的文件）
3. **跨文件"小批量"改完用 grep 全量核对**：搜索模块顶部 import、新挂的依赖等"改动符号"做发现性校验
4. **整文件块比较大动时**（import + 全接口挂依赖）用整文件覆盖（Write 整体重写），比多次 SearchReplace 更稳健
5. 不要相信"工具返回 file_changes"代码块里的 diff —— 它只是工具认为的子集；必须用 Read/Grep 从磁盘独立校验

## 验证

（自本条方案段提取）每文件改完 Read 回读一次；跨文件小批量改完用"改动符号"（模块顶部 import、新挂依赖等）grep 全量核对；一切以 Read/Grep 从磁盘读到的内容为准，不采信工具返回的 diff 子集。

## 适用边界与反例

M5 后端 6 路业务路由挂 require_perm——clients/customers/algorithm/exports/models/documents 7 文件接到同一轮 tool call 同时处理，最终 models.py + exports.py 整文件要重写才能修好。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
