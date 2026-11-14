---
id: kb-20261114-b226
title: 联邦 L2 记录契约：index.jsonl 行是外部异构源接入的唯一接口
type: reference
domain:
- backend
tags:
- 联邦契约
- 联邦 L2
- 记录契约
- 外部源接入
- index.jsonl
- federation-contract
- federated-l2
- origin
- uri
- external-source
- promote-to:stack
- needs-scope-review
- promoted
- auto-reviewed
source:
  project: agent-kb
  ref: docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md#2
created: '2026-11-14'
scope: project
status: accepted
confidence: verified
updated: '2026-11-14'
summary: 外部异构源接入只需产出含 origin/uri 的 index.jsonl 行；本地条目恒为 origin=local、uri=null，检索与
  lint 面零改动。
review_by: '2027-11-14'
revision:
  reason: content-edited
  from_status: accepted
  at: '2026-11-14'
verified_by: agent
verification:
  evidence: '终审 F4 措辞修正: 正文 grep 实测全仓除 index.py 注入点外无 origin 消费点, stats.source_of
    仍按 source:// 前缀判源; 补注过渡态说明。tests/test_index.py + tests/test_federation_contract.py
    全绿(2026-11-14)'
  reviewed_at: '2026-11-14'
---

# 联邦 L2 记录契约：index.jsonl 行是外部异构源接入的唯一接口

## 结论卡
`kb/index.jsonl` 每行 = 一条联邦 L2 记录。外部异构源(飞书/Notion/wiki/TencentDB-Agent-Memory…)
接入的唯一义务是**产出该形状的 JSONL 行**: 新增 `origin`/`uri` 两键后, 本地条目恒为
`origin: "local"`、`uri: null`, 检索与 lint 面零改动——本地面只是该契约的第一个实现。

## 定义
在现有记录字段(`_records` 产物: id/title/type/domain/tags/scope/status/severity/confidence/
path/summary/keywords/sections/dedup_key/related/updated/repo)之上新增两字段:

| 字段 | 含义 | 本地取值 |
| --- | --- | --- |
| `origin` | 来源命名空间 | `"local"` |
| `uri` | 回源定位符(外部源给可回读的 URI) | `null`(本地靠 repo+path 回源) |

- **id 双命名空间**: 沿用 stats.py `source_of()` 既有约定——外接命中 id 形如
  `source://<connector>/<原生id>`, 归一化 `ext:<connector>`。本地 id 不变(`kb-YYYYMMDD-xxxx`)。

## 用法
- **适配器唯一义务**: 产出该形状的 JSONL 行。外部条目**不进** front-matter/lint/六段骨架
  体系; `sections`/`keywords` 等派生字段对外部源可为空。
- 消费方(检索/面板)按 `origin != "local"` 即视为外接, 不猜前缀。
  **本期实现状态**: 该判定是契约声明, 尚无消费点读 `origin`(全仓仅 `index._records`
  注入); 在位的判源仍是 `stats.source_of()` 按 `source://` **前缀**归类。两套判据并存
  属过渡态, 消费侧切到 `origin` 待首个 connector 落地时一并做。
- 索引重建零漂移: 存量条目重建后除 `origin`/`uri` 两字段外逐字节不变。
- 本地行两字段的注入点在 `src/kb/index.py` `_records`(本仓唯一的记录生产者注入点)。

## 示例
```json
{"id": "kb-20261114-xxxx", "origin": "local", "uri": null, "repo": "agent-kb", "…": "其余既有字段照旧"}
{"id": "source://feishu/wiki-123", "origin": "ext:feishu", "uri": "https://….feishu.cn/wiki/wiki-123", "sections": [], "keywords": []}
```

## 本期不做
任何 connector 实现、外部源索引合并逻辑、`origin` 参与打分。本期只保证本地记录带
`origin:"local", uri:null` 且消费方按此判定外接。

## 参考
- 契约事实源: `docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md` §2
- 回归测试: `tests/test_index.py::test_records_carry_federation_fields`(本地行两字段)、
  `tests/test_federation_contract.py`(CLI/MCP 形状一致 + returned_chars compact 口径)
