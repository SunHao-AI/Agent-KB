---
id: kb-20261021-d3d2
title: traces 分片缺 meta 首行导致整文件事件被静默跳过
type: pitfall
domain:
- devops
tags:
- auto-reviewed
scope: project
status: accepted
confidence: verified
created: '2026-10-21'
updated: '2026-10-21'
severity: medium
verified_by: agent
verification:
  evidence: '复现: 无 meta 首行的分片注入后 /api/callers 读不到; 补 meta 行后立即可见且 stale=true; 根因 kb/trace.py
    _parse_file 缺 meta 首行整文件跳过'
  reviewed_at: '2026-10-21'
---

# traces 分片缺 meta 首行导致整文件事件被静默跳过

## 背景

给观测面板注入历史 trace 测 stale 标记: 直接向 `traces/<date>.jsonl` append 了一条 search 事件, 但面板与 `/api/callers` 完全读不到该 caller, 无任何报错。

## 根因

`kb.trace._parse_file` 要求每个 traces 分片文件**首行必须是 `{"kind":"meta","schema":N,...}`**, 缺 meta 首行的文件整体跳过(只进 warns 列表)。warns 仅在面板 stats 横幅和 `kb trace` 部分命令里展示, 直接读 API/面板时不可见, 表现为"静默丢数据"。

## 正确姿势

手工构造 trace 文件时先写一行 meta:

```json
{"kind": "meta", "schema": 2, "repo": "<名>"}
{"kind": "search", ...}
```

schema 高于本地 SCHEMA 同样整文件跳过。append-only 语义下不要重写既有文件首行。

## 教训

"整文件跳过 + 警告藏在次要出口"是数据静默丢失的经典组合; 读侧对缺 meta 至少应在 `/api/health` 或 stats 顶层 warns 暴露(现状 stats warns 可用, 排查时记得看)。
