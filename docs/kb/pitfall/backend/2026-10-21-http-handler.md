---
id: kb-20261021-8a2f
title: HTTP handler未兜底异常穿透致连接裸断且外部数据文件须解析期归一化
type: pitfall
domain:
- backend
tags:
- http
- error-handling
- defensive-parsing
- auto-reviewed
scope: project
status: accepted
confidence: verified
created: '2026-10-21'
updated: '2026-10-21'
severity: medium
verified_by: agent
verification:
  evidence: tests/test_trace.py::test_read_coerces_dirty_types_and_warns + tests/test_stats_serve.py::test_serve_survives_dirty_events(修复前三端点连接裸断,
    修复后 200); §26 浏览器实测 watcher 存活; pytest 280 全过
  reviewed_at: '2026-10-21'
---

# HTTP handler未兜底异常穿透致连接裸断且外部数据文件须解析期归一化

## 背景 / 现象
观测面板 serve 的 trace 文件混入脏数据(`returned: null`、`chars: "abc"`)后,
`/api/stats`、`/api/feed`、`/api/callers` 三端点**连接被直接掐断**——客户端报
"无法连接到远程服务器", 而不是 500。面板端只剩转圈, 无任何可提示的错误体。
同时 SSE watcher 遇 JSON 数组行(`[1,2,3]`)抛 AttributeError, 该 tick 剩余合法事件全丢。

## 根因
三层防线同时缺失:
1. **读侧信任边界错位**: trace 文件由各业务仓客户端/手工写入, 属不可信输入,
   但 `read_traces` 只防御了 JSON 解析失败(`json.JSONDecodeError`), 未防"合法 JSON
   但类型错"——`len(None)`/`int("abc")` 把 TypeError 直接抛给上层。
2. **handler 兜底不全**: `do_GET` 的 try 只 `except BrokenPipeError`, 其余异常穿透到
   `BaseHTTPRequestHandler`, 响应头未发出连接即断 → 客户端看到的是"连不上"而非 500,
   可观测性比 500 更差(无错误体, 排障只能靠服务端 stderr, 而生产常静音)。
3. **后台线程逐行无守卫**: watcher 对每行 `ev.get("kind")` 假定是 dict,
   JSON 数组/标量行使 `_tick` 中途抛出, 文件偏移已推进 → 该批事件永久丢失。

## 解决方案
- **解析期归一化**: 在解析函数内(对象尚未入缓存、私有时)把"会让算术崩"的类型归一
  (null/非列表→[]、非数值→None)并记告警; 语义脏值(负数、怪字符串)如实呈现不篡改。
  注意: 若解析结果进共享缓存(契约"入缓存后只读"), 归一必须在入缓存前做, 消费侧禁改。
- **handler 兜底**: `except BrokenPipeError: pass` 之后追加 `except Exception` 回 500
  带错误体——错误不可怕, 不可提示才可怕。
- **后台线程逐行 `isinstance(ev, dict)` 守卫**, 脏行 continue, 不连坐同批好数据。

## 验证
- 单测(`tests/test_trace.py::test_read_coerces_dirty_types_and_warns`): 脏类型归一 +
  告警 + `stats.aggregate` 不再 TypeError;
- serve 级回归(`tests/test_stats_serve.py::test_serve_survives_dirty_events`): 同一份脏
  文件下三端点全 200(修复前连接裸断);
- 浏览器端到端(§26): watcher 在 3 条非对象行后仍存活推送(10/10→11/11)。

## 适用边界与反例
- 适用于: 一切"读外部落盘数据 + HTTP 出数"的服务(观测/报表/导入), 尤其数据由多个
  客户端写入、无法保证写侧纪律的场景。
- 不适用: 纯内部生成、有 schema 校验(如 protobuf/pydantic 入口)的数据管道——校验应
  在写侧入口做, 读侧不必重复。
- 反例提醒: 归一化只处理"类型导致崩溃", 不要顺手"修正"语义(如把负耗时改成 0),
  那会掩盖真实数据质量问题; 告警列表要能透出给人看。

## 参考
- 测试记录: `docs/tests/2026-10-21-full-coverage-test.md` §26
- 修复提交: `b003c0e` (src/kb/trace.py `_coerce` / src/kb/serve.py)
