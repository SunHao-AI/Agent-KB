---
id: kb-20261021-1b60
title: append-only trace 账本读侧裸取字段致 API 线程 KeyError 掐连接
type: pitfall
domain:
- backend
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
  evidence: serve stderr 抓到 KeyError title traceback(spider_export.py L57); 回归测试 test_spider_export.py::test_sparse_legacy_trace_no_crash
    先失败后通过; 浏览器实测稀疏 trace 全屏桥修复后 iframe 正常, /api/replay 由断连变 200
  reviewed_at: '2026-10-21'
---

# append-only trace 账本读侧裸取字段致 API 线程 KeyError 掐连接

## 背景

观测面板点"全屏蜘蛛回放"显示 `全屏不可用: Failed to fetch`, 浏览器控制台只有 net::ERR_EMPTY_RESPONSE; curl 同一 URL 同样"连接被意外关闭"。用仿真脚本生成的 trace 一切正常, 手工 append 的最小 trace 一触即炸。

## 根因

导出层 `spider_export.to_record` 以"写方是自己"的隐含契约直接 `m["title"][:40]`、`l['rejected']['filter']` 裸取字段; 而 traces/*.jsonl 是 append-only 账本, 历史分片/手工构造/早期 schema 的事件天然可能缺这些键。KeyError 在 HTTP 线程未捕获 → 连接裸掐, 客户端只能看到"Failed to fetch", 错误形态与网络故障无法区分(traceback 只落在 serve stderr)。

## 修复

读侧一律 `.get` 防御 + 语义回退(title 缺失回退 id, rejected 子键回退 0), 与同文件 `_detail` 既有的"历史 trace 缺字段不得炸"先例对齐; 回归测试 `test_sparse_legacy_trace_no_crash` 用最小稀疏 trace 锁死。

## 教训

对 append-only 事件账本, 读侧必须按"最稀疏的历史形态"防御, 写方当前字段齐全不构成读方假设; 且 API 线程未捕获异常的表现是断连而非 500, 排障时浏览器看不到真因, 必须回看服务端 stderr/日志。
