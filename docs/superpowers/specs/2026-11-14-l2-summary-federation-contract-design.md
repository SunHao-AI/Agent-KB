# L2 摘要质量优化与联邦 L2 记录契约设计

- 日期: 2026-11-14
- 状态: 已批准(2026-11-14, 含落地前实读取证修正: §3.1 schema 真源=taxonomy.py::derive_schema、§3.2 Entry.summary 现纯派生需新增显式分支、§4 埋点已 compact 零改动)
- 范围: 范围 1 —— 只改本地面(index/schema/lint/templates/CLI/MCP 提示/stat), 但按联邦契约定死 L2 记录形状; 不写任何外部源适配器

## 1. 背景与根因

数据实锤(traces/*.jsonl 全量, 2026-11-14 实测): `kb stat` 聚合口径下
meta_only **503 次 / 2,211,407 字**, meta_to_full 113 次 / 34,601 字——
**81.7% 的有返回检索止步于 L2**, Agent 命中即消费摘要收尾, L3 下钻 11-04 后归零。
L2 已实质成为**最终消费面**, 但当前 L2 摘要(`Entry.summary()` 派生: 正文首段
首句截 120 字)只是"开头", 不是"结论", 消费面质量与消费地位错配。

全库 207 条(accepted)中显式 `summary:` 字段为 **0 条**(Grep 实锤)。

方案裁决(已批准=甲): **front-matter 显式 `summary` 字段为体 + lint 渐进守护为用 +
stat 度量为闭环**。业界对齐: schema.org `description` / OG `og:description` /
Atom `summary` / Jekyll excerpt / Backstage `metadata.description` / Anthropic
skills description——L2 摘要在主流系统中一律是**头部显式声明**, 无系统靠"正文第一段"
当最终消费面。否决项: 按六段骨架机械抽取结论(外部源不守骨架即失效, 与联邦愿景冲突)、
仅下发 sections + 引导文案(治标, 消费面质量仍靠猜)。

项目愿景约束: 知识库后续接入外部源(飞书/Notion/wiki/TencentDB-Agent-Memory),
故 L2 记录形状本期定死为**联邦归一化契约**, 本地面是契约的第一个实现。

## 2. 联邦 L2 记录契约(§1 段, 已确认)

**唯一事实源**: 本 spec §2; 落地时在 `AGENTS.md`"常用命令"附近加一句指向, 不另立
独立契约文档(避免第二事实源漂移; 外部适配器出现时再评估拆出)。

`kb/index.jsonl` 每行 = 一条联邦 L2 记录。在现有记录字段(_records 产物:
id/title/type/domain/tags/scope/status/severity/confidence/path/summary/keywords/
sections/dedup_key/related/updated/repo)之上**新增两字段**:

| 字段 | 含义 | 本地取值 |
| --- | --- | --- |
| `origin` | 来源命名空间 | `"local"` |
| `uri` | 回源定位符(外部源给可回读的 URI) | `null`(本地靠 repo+path 回源) |

- **id 双命名空间**: 沿用 stats.py `source_of()` 既有约定——外接命中 id 形如
  `source://<connector>/<原生id>`, 归一化 `ext:<connector>`。本地 id 不变(`kb-YYYYMMDD-xxxx`)。
- **适配器唯一义务**: 产出该形状的 JSONL 行。外部条目**不进** front-matter/lint/
  六段骨架体系; `sections`/`keywords` 等派生字段对外部源可为空。
- **本期不做**: 任何 connector 实现、外部源索引合并逻辑、`origin` 参与打分。
  本期只保证: 本地记录带 `origin:"local", uri:null`, 消费方(检索/面板)按
  `origin != "local"` 即视为外接, 不猜前缀。

新增字段的索引重建零漂移要求同 §5(存量条目重建后除这两字段外逐字节不变)。

## 3. summary 字段与生成链路(§2 段, 已确认)

### 3.1 schema

运行时校验 schema 的**唯一真源**是 `src/kb/taxonomy.py::derive_schema()`(lint 用
`jsonschema.Draft202012Validator(derive_schema(load_taxonomy()))` 校验);
`schema/frontmatter.schema.json` 无代码加载, 属文档性文件, 仅同步不改行为。

`derive_schema()` 的 properties 加(文档 schema 同步):

```json
"summary": { "anyOf": [
  { "const": "" },
  { "type": "string", "minLength": 10, "maxLength": 300 }
] }
```

**不进 required**; "空 = 缺失"([entry.py](../../src/kb/entry.py) `Entry.summary()`
判断 `fm.get("summary")` strip 后非空): 空串显式豁免(模板 `summary: ""` 占位与
人工清空都合法), 1–9 字符与 >300 字符为 schema 硬错误。长度下限 10 防"填了等于
没填", 上限 300 对齐 OG 惯例并给结论句留空间(120 太短写不下"条件+结论+动作")。

### 3.2 Entry.summary() 单点收口

现状([entry.py](../../src/kb/entry.py) `Entry.summary()`, 实读取证): **纯派生**——
按空行分块取第一个有正文的块折叠空白后 `[:limit]`, **没有任何 `fm["summary"]` 分支**
(显式字段此前根本不被读取)。改为:

- **新增**显式分支(方法首部): `fm.get("summary")` 非空则仅折叠空白返回,
  **不做 120 截断**(显式声明即最终消费文案, schema 已限 300);
- 派生兜底分支: **逐字节不变**(首段首句 + limit), 由回归测试锁定。

`build_index`/`INDEX.md`/检索面全部经 `Entry.summary()` 单点取值, 无需感知改动。

### 3.3 lint 渐进守护(甲-1)

`lint.py` 新增 **warning**(不红灯、不挂门禁): `created >= SUMMARY_REQUIRED_SINCE`
(模块常量, 取 `2026-11-15`, 即本 spec 落地次日)的条目缺显式 `summary` 即告警。
存量条目(created 早于该线)自然豁免, **不做批量回填**、不做六段抽取预填。

> **落地口径修正(2026-11-14 终审, 两处偏离初稿均已确认)**
>
> 1. **判界字段取 `created` 而非初稿的 `updated`**: 按 `updated` 判界会让存量条目因一次
>    错别字修订就冒出告警, 与"存量不追"的意图冲突; `created` 才表达"这条条目是否
>    新规时代出生"。实现与计划本就用 `created`, 此处回写 spec 而非改代码。
> 2. **"缺 summary" 按**值**判(strip 后为空即缺失), 不是按"键不存在"**: 初稿对此未定义,
>    实现取了"键存在即已声明", 后果是守护线被自己的模板屏蔽——§3.4 给 8 个模板都加了
>    `summary: ""`, 照模板建档的条目天然带空串键, 永远报不出来。改为按值判后与
>    `Entry.summary()` 的"空 = 缺失"取值语义、`query.stat` 的显式覆盖计数三处同口径;
>    schema 仍放行空串(占位与人工清空合法), 只是 lint 会对新条目提示补写。

### 3.4 生成端提示

- `templates/*.md` 全部 8 个模板 front-matter 加 `summary: ""` 占位 + 行内注释
  (一句话结论: 条件→结论→动作);
- `kb new --generated` 与 MCP `kb_create` 的返回/description 提示补一句"建议补写
  summary 结论句", **不强制**(强制违背 draft→终审门控既有节奏)。

## 4. 返回面(§3 段, 实测修正版)

实测(`kb search --query "pre-push 门禁" --repo docs --no-trace --limit 1`)推翻两项
纸面勘察, 均**零改动**:

- **sections 本就在返回**: `search.evaluate()` 的 `rows = [h[2] for h in hits]` 是
  index.jsonl 整行透传, 无裁列; sections 还以权重 1.5 参与命中。其 80 字符硬截断
  瑕疵因结论面改由显式 summary 承担而降级为不修。
- **协议引导不做**: MCP 面 kb_search/kb_get 工具并列已是业界渐进披露标准形态,
  Agent 止步 L2 是理性消费而非引导缺失——引导文案治不了"摘要不值得下钻"。

埋点口径实读取证(修正纸面勘察): [cli.py](../../src/kb/cli.py#L353)
`returned_chars=len(json.dumps(res, ensure_ascii=False))` **本就是 compact 口径**
(`indent=2` 只出现在 L355 的 stdout 打印, 不进埋点)——与 MCP 面已天然对齐,
**零改动**。仅加一条回归断言锁定该口径(埋点值 == compact dumps 值), 防未来
有人把打印口径混进字符账。

## 5. 观测闭环与测试面(§4 段, 已确认)

### 5.1 基线(现成, 零新增埋点)

meta_only 503 次 / meta_to_full 113 次(81.7% 只看元数据)、显式 summary 覆盖 0/207。
上线后直接对比这两组数, 不建新指标、不加 trace 字段、不动面板。

### 5.2 唯一新增度量: L2 结论覆盖率

`kb stat` 输出加 `summary_coverage: {"explicit": N, "total": M}`。判据 = 条目的
front-matter 有无非空 `summary`。落点: [query.py](../../src/kb/query.py) `stat()`
现读 index.jsonl(拿不到 fm 的显式性), 故在 stat 内以 `iter_entry_paths` +
`parse_entry` 直接遍历条目计数(207 条量级无性能问题)——**不进 index.jsonl**
(不往检索面掺度量字段, 也免去又一处索引漂移源)。不设阈值告警——守护线是
§3.3 lint warning, stat 只是读数。

### 5.3 测试面清单

1. **零漂移回归**: 存量库(无显式 summary)重建索引, `kb index --check` 除新增
   `origin`/`uri` 两字段外逐字节零漂移; 派生 summary 路径输出逐字节不变;
2. **schema 边界**: summary 长度 9/10/300/301 四例进 lint 用例(9/301 红灯);
3. **lint warning**: `updated` ≥ 2026-11-15 缺 summary 告警、旧条目豁免、
   warning 不使 `kb lint` 退出码变红;
4. **Entry.summary() 单测**: 显式值仅折叠空白不截断(300 字原文透传)、
   派生路径既有断言不动全绿;
5. **returned_chars compact 断言**: CLI 埋点值 == `len(json.dumps(res,
   ensure_ascii=False))`(compact), 且 ≠ indent 口径;
6. **summary_coverage 读数**: 0 显式 / 部分显式两种 fixture 的 N/M 断言;
7. 既有全量测试套跑绿 + `kb index --check` CI 门禁过。

## 6. 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `src/kb/taxonomy.py` | `derive_schema()` +summary 属性(10–300, 非必填)——**运行时 schema 真源** |
| `schema/frontmatter.schema.json` | 文档同步 +summary 属性(无代码加载) |
| `src/kb/entry.py` | `Entry.summary()` **新增**显式分支(不截断), 派生路径不动 |
| `src/kb/index.py` | `_records` rec +`origin`/`uri` 两字段 |
| `src/kb/lint.py` | +SUMMARY_REQUIRED_SINCE warning |
| `src/kb/cli.py` | 零改动(埋点已 compact), 仅回归断言 |
| `src/kb/mcp_server.py` | kb_create description 提示一句 |
| `templates/*.md`(8 个) | front-matter +`summary: ""` 占位 |
| `AGENTS.md` | 一句话指向联邦契约节(§2) |
| `src/kb/query.py` | `stat()` +`summary_coverage` 读数(直接遍历条目) |
| `docs/tests/...` / 既有测试 | §5.3 用例落点按既有测试布局就近追加 |
