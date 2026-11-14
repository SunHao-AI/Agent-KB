---
id: kb-20261114-b226
title: 联邦 L2 记录契约：index.jsonl 行形状已定版，外部行直写接入尚未实现
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
- 外部行被重建清除
- 直写索引
- connector 未实现
- 接入前置条件
- row-wiped-by-index
- not-implemented
- external-row-merge
- auto-reviewed
source:
  project: agent-kb
  ref: docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md#2
created: '2026-11-14'
scope: stack
status: accepted
confidence: verified
updated: '2026-11-15'
summary: '联邦 L2 记录形状已定(本地行 origin=local/uri=null), 但"适配器直写 index.jsonl"只是目标契约而非可用路径:
  直写行会被 kb index 重建静默清除, 并使 stat/show 抛 KeyError、index --check 恒 stale——接 connector
  前须先补索引合并与消费面容错。'
review_by: '2027-11-14'
revision:
  reason: content-edited
  from_status: accepted
  at: '2026-11-15'
verified_by: agent
verification:
  evidence: '2026-11-15 实测 @9e90a90: 契约示例最小外部件直写 index.jsonl → kb stat 抛 KeyError
    ''type''、kb show 抛 KeyError ''path''、index --check rc=1 恒 stale, 且一次 kb index
    后该行被清除(grep source:// = 0)。标题原称"唯一接口"与实测相反, 已改为"形状已定/直写接入尚未实现"; 正文新增「接入前置条件」节。'
  reviewed_at: '2026-11-15'
---

# 联邦 L2 记录契约：index.jsonl 行形状已定版，外部行直写接入尚未实现

## 结论卡
`kb/index.jsonl` 每行 = 一条联邦 L2 记录, 其**记录形状**(`origin`/`uri` 两键)已定版:
本地条目恒 `origin: "local"`、`uri: null`。但"适配器唯一义务 = 直写该形状 JSONL 行"
目前是**目标契约, 不是可用的接入路径**——直写行会在下一次索引重建时被静默清除, 并打挂
本地消费面(见"接入前置条件")。

## 定义
在现有记录字段(`_records` 产物: id/title/type/domain/tags/scope/status/severity/confidence/
path/summary/keywords/sections/dedup_key/related/updated/repo)之上新增两字段:

| 字段 | 含义 | 本地取值 |
| --- | --- | --- |
| `origin` | 来源命名空间 | `"local"` |
| `uri` | 回源定位符(外部源给可回读的 URI) | `null`(本地靠 repo+path 回源) |

- **id 双命名空间**: 沿用 stats.py `source_of()` 既有约定——外接命中 id 形如
  `source://<connector>/<原生id>`, 归一化 `ext:<connector>`。本地 id 不变(`kb-YYYYMMDD-xxxx`)。

## 用法(形状约定)
- 外部条目**不进** front-matter/lint/六段骨架体系; `sections`/`keywords` 等派生字段
  对外部源可为空。
- 消费方(检索/面板)按 `origin != "local"` 即视为外接, 不猜前缀。
  **实现状态**: 该判定是契约声明, 尚无消费点读 `origin`(全仓仅 `index._records` 注入);
  在位的判源仍是 `stats.source_of()` 按 `source://` **前缀**归类。两套判据并存属过渡态。
- 本地行两字段的注入点在 `src/kb/index.py` `_records`(本仓唯一的记录生产者注入点)。
- 索引重建零漂移: 存量条目重建后除 `origin`/`uri` 两字段外逐字节不变。

## 接入前置条件(尚未实现, 直写 = 自锁)
2026-11-15 实测(把下文示例行追加进 `kb/index.jsonl` 后):

1. **`kb index` 整体重生成该文件**: 外部行会在下一次任何索引重建(含 `kb new` /
   `kb_update` 内部的 `_reindex`)被**静默清除**——不报错也不告警。CLI 没有合并外部行
   的入口。
2. **打挂本地消费面**: 契约示例的最小外部件(无 `type`/`status`/`path`)使 `kb stat` 抛
   `KeyError: 'type'`(`query.stat` 的 `Counter(r["type"] …)`), `kb show <id>` 抛
   `KeyError: 'path'`(`query._find_path`)。`kb search` 因走 `.get` 不受影响。
3. **`index --check` 恒判 stale**: `check_indexes` 按 markdown 逐条重算比对, 外部行不在
   重算结果内即整仓 stale(其容差只覆盖"本地行缺 `origin`/`uri`"的跨仓形状版本场景)
   → 该仓每次推送被 pre-push 门禁拦下。

即"履行契约"与"门禁可用"当前**互斥**。真接 connector 前需先在 spec 定案并落地三件事:
索引合并保留外部行 + 消费方对非 local 行容错 + `check_indexes` 跳过非 local 行;
或反向把 `type`/`status`/`domain`/`path` 定为外部行**必填**并给适配器映射规则。

## 示例
```json
{"id": "kb-20261114-xxxx", "origin": "local", "uri": null, "repo": "agent-kb", "…": "其余既有字段照旧"}
```
外部行形状(**尚无生产者**; 直写的前置条件见上节, 未满足前勿直写):
```json
{"id": "source://feishu/wiki-123", "origin": "ext:feishu", "uri": "https://….feishu.cn/wiki/wiki-123", "sections": [], "keywords": []}
```

## 本期不做
任何 connector 实现、外部源索引合并逻辑、`origin` 参与打分。本期只保证本地记录带
`origin:"local", uri:null` 且消费方按此判定外接。

## 参考
- 契约事实源: `docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md` §2
- 回归测试: `tests/test_index.py::test_records_carry_federation_fields`(本地行两字段)、
  `tests/test_federation_contract.py`(CLI/MCP 形状一致 + returned_chars compact 口径)、
  `tests/test_index.py::test_check_tolerates_v1_rows_missing_origin_uri`(跨仓 v1 行兼容)
