---
id: kb-20261026-2d9c
title: 'hgetall 返回 bytes 键未归一: str 键取值永远 miss, FakeRedis 假件测不出'
type: pitfall
domain:
- backend
tags:
- promoted
scope: stack
status: accepted
confidence: probable
created: '2026-10-26'
updated: '2026-10-26'
severity: medium
verification:
  evidence: '代码审查发现+修复落地: flysee_video_web backend/services/imagepush_service.py _hgetall_str;
    复现口径 hgetall(k).get(''state'')=None vs .get(b''state'')=b''active''(未开 decode_responses);
    修复后 web 全量回归 771 passed 1 skipped'
  reviewed_at: '2026-10-26'
source:
  project: docs
---

# hgetall 返回 bytes 键未归一: str 键取值永远 miss, FakeRedis 假件测不出

## 背景 / 现象

flysee_video_web 仓 `backend/services/imagepush_service.py`(图片推流会话 hash)开发时,
`hgetall` 结果用 `sess.get("state")` 这类 **str 键**取值。单测(FakeRedis 假件)全绿,
但对接真实 Redis 后 session_state 永远读成缺省值——推图鉴权绑定、会话状态机全部失效。
代码审查时发现, 未流入生产。

## 根因

web 侧 `get_redis()` 连接池**未开** `decode_responses=True`, redis-py 默认返回
`bytes` 键 + `bytes` 值。`h.get("state")`(str 键)与 `b"state"`(bytes 键)在 dict 里
是两个不同键, 取值永远 miss。既有代码只用 `hget`/`hset`(单键由客户端传入, redis-py
自动编码 bytes), 从未整取 hash, 所以坑首次在 `hgetall` 消费方爆雷。

## 解决方案

统一归一助手, 键与值都解码:

```python
def _hgetall_str(self, key: str) -> dict[str, str]:
    raw = self.redis.hgetall(key) or {}
    return {self._sval(k): self._sval(v) for k, v in raw.items()}
```

(`_sval` = bytes 则 `decode("utf-8", "replace")`, str 原样, 其他 str() 兜底。)
不要图省事只归一值——**键**才是本陷阱主体。

## 验证

- 复现口径: 真连一个未开 decode_responses 的 Redis, `hset(k, "state", "active")` 后
  `hgetall(k).get("state")` → None, `.get(b"state")` → `b"active"`。
- 修复后 web 全量回归 `uv run --no-sync pytest -q` 771 passed(镜像测试见下条反例)。

## 适用边界与反例

- 适用于任何未开 `decode_responses` 的 redis-py 客户端消费 `hgetall`/`hkeys`/`scan_iter`
  等**返回键面**的命令; 只写单键命令(hget/hset/expire)不受影响。
- **测试假件盲区**: 自研 FakeRedis 若键用 str 存(本仓即如此), 此 bug 测不出——
  假件应与真实客户端的编码行为对齐, 或补一条真连 Redis 的契约测试。
- 同理 `keys()`/`scan` 返回值拼前缀比较前也要解码。

## 参考

- flysee_video_web 仓 `backend/services/imagepush_service.py` `_hgetall_str`;
  redis-py 文档 decode_responses(默认 False)
- 关联: kb-20261012-d3e8(跨服务契约字段错配, 同为"两侧编码/命名口径不一致"族)
