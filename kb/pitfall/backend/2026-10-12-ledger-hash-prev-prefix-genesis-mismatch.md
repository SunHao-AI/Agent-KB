---
id: kb-20261012-3194
title: 履历链哈希跨仓漂移：校验侧丢 prev 前缀 + genesis 哨兵口径不一
type: pitfall
domain:
- backend
tags:
- hash-chain
- cross-repo
- genesis
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-10-12'
updated: '2026-10-18'
review_by: '2027-04-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/授权与台账.md
---

# 履历链哈希跨仓漂移：校验侧丢 prev 前缀 + genesis 哨兵口径不一

## 背景 / 现象

（自本条根因段提取）web 签名侧与 setting 校验侧各自单测全绿，但端到端一拼即全红：对端上报的真实履历链全部被判 `chain_broken`；链首 prev 的取值两侧也不一致（`""` vs `"0"*64`）。

## 根因

**根因**：追加式哈希履历链的链式哈希，web 签名侧（`flysee_video_web/backend/license/ledger.py::_entry_hash`）算的是 `sha256(prev_hash + canonical(entry))`，而 setting 校验侧（`backend/services/license_audit_service.py::entry_hash`）只算了 `sha256(canonical(entry))`——**漏掉 prev 前缀**，等于放弃了链式防篡改语义，且对端上报的真实链全部判 `chain_broken`。次生漂移点：链首 prev 的口径 setting 期望空串 `""`，web 首条 prev 写 `GENESIS = "0"*64` 哨兵。两侧单测各自绿（各测各的口径），端到端一拼即全红——跨仓契约没有共享实现也没有契约测试锁字面值时必然漂移。

## 解决方案

**解决方案**：以**签名侧（web）为准**统一校验侧——`entry_hash` 补回 prev 前缀，并引入与 `ledger.py::GENESIS` 同值的 `GENESIS = "0" * 64` 常量作链起点哨兵（`expect_prev = last.hash if last else GENESIS`）。修复后用真实数据做端到端重放验收：取 client 16 已上报的 200 条 events，向哨兵 client_id 重放，断言 `accepted == 200` 且 `chain_broken == False`（仅单测构造链不足以证明跨仓一致）。

**代码示例**（`backend/services/license_audit_service.py`）：

```python
# 必须与客户端 ledger.py::GENESIS 同值, 改一处必须两仓同步
GENESIS = "0" * 64

def entry_hash(seq: int, event: str, data, prev_hash: str) -> str:
    canonical = canonical_entry(seq, event, data, prev_hash)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()
```

## 验证

真实数据端到端重放验收：取 client 16 已上报的 200 条 events，向哨兵 client_id 重放，断言 `accepted == 200` 且 `chain_broken == False`（原文「解决方案」段）。

## 适用边界与反例

**要点**：
- 端到端重放脚本首轮 `accepted=0` 曾误导判断——裸 SQL 读 JSON 列返回**字符串**，而线上 ORM 通道返回 **dict**，`json.dumps(default=str)` 对两者产出不同 canonical。重放脚本必须先 `json.loads(row["data"])` 归一为 dict 再校验。这是取证脚本自身的坑，非产品缺陷；凡"绕过 ORM 复现线上行为"的脚本都要对齐列类型通道。
- 测试断链用例的 prev 改动要同步改哨兵语义：断链篡改用 `"1"*64` 而非 `"0"*64`，否则会把"首条 prev 应等于 GENESIS"误判成断链。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权与台账.md`
