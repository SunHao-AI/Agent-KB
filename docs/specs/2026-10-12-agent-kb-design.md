# Agent-KB 研发知识沉淀体系设计方案

| 项 | 内容 |
| --- | --- |
| 文档类型 | 设计规格（Design Spec） |
| 版本 | v1.0 |
| 日期 | 2026-10-12 |
| 状态 | 待评审（proposed） |
| 范围 | 跨项目通用的研发知识沉淀体系，面向人 + AI Agent 双消费 |

---

## 1. 背景与目标

### 1.1 背景

当前 `flysee-video-setting`、`flysee_video_web`、`flysee_video_algorithm` 三个仓库各自维护了一套 `docs/known-pitfalls/`（`README.md` 摘要索引 + 分类主题聚合文件），已具备"分层索引"雏形，但存在四个缺口：

1. **无机器可读元数据** —— Agent 必须读正文才能判断相关性，token 浪费。
2. **无跨项目共享机制** —— 每个新项目都要重新搭一遍，通用经验无法复用。
3. **无检索/校验自动化** —— 索引靠手工维护，易漂移；无 lint、无去重。
4. **无生命周期治理** —— 条目没有状态、时效、废弃概念，过时内容会污染 Agent 上下文。

### 1.2 目标

设计一套**可被 AI Agent 高效读取、解析、调用、更新**的研发知识沉淀体系，覆盖开发全流程知识（设计文档、技术方案、问题排查、BUG 根因、解决方案、经验总结），并满足：

- **专业性**：有分类标准、结构化规范、质量门控。
- **规范性**：统一元数据契约与模板，机器可校验。
- **可复用性**：通用知识与项目知识分层，一套系统服务所有项目。
- **低 token**：Agent 按需加载，不把知识全量塞进常驻上下文。

### 1.3 非目标（YAGNI）

- 不做服务端/数据库存储（本地文件优先，零外部依赖起步）。
- 不做全量向量检索（仅在关键词检索命中率不足时按需叠加）。
- 不替代现有 `docs/superpowers/specs|plans` 工作流，而是纳入统一入口。

---

## 2. 调研结论（设计依据）

调研覆盖 ADR/Docs-as-code/结构化笔记/事故复盘、Agent 记忆与工程知识项目、元数据与治理标准，以及 Notion/飞书能力与 Anthropic/OpenAI 上下文工程实践。关键结论：

1. **业界共同模式**：`纯文本 Markdown + 头部元数据(front-matter) + 分层索引 + 渐进式披露 + 按需加载`。代表：Anthropic Agent Skills（三级披露）、AGENTS.md（nearest-file-wins）、Cursor rules。
2. **token 效率**：Anthropic 官方主张"找到最小的高信号 token 集合"，上下文是有限注意力预算，token 越多越"context rot"。分层索引/按需加载相比全量注入实测省 **40%–88%**；prompt caching 最多降本 90%。
3. **重型方案不适用**：Mem0 / Zep / Graphiti / GraphRAG / RAGFlow 属"运行时记忆 / 大规模语料问答"，依赖服务端、成本高（GraphRAG 500 页语料约 $50–200），不适合工程知识沉淀。
4. **Notion / 飞书 不做主存储**：闭源 SaaS、块(block)树结构读取冗余（Notion 实测纯文本读取可省 3–15× token）、diff 与追溯弱于 git。飞书**多维表格 Base** 是三者中唯一"机器可读的结构化库"（强类型字段 + filter 公式检索），可做**元数据索引层/协作镜像**。
5. **无即插即用的"研发知识库系统"**：成熟件只提供片段（ADR 模板、Diátaxis 分类、SRE postmortem 字段、本地 markdown + MCP 检索）。因此采用"**采纳标准 + 复用组件 + 薄自研层**"。

主要来源：
- Anthropic — [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)、[Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [AGENTS.md](https://agents.md/)、[Diátaxis](https://diataxis.fr/)、[MADR](https://adr.github.io/madr/)、[Google SRE Postmortem](https://sre.google/sre-book/postmortem-culture/)、[Git submodules](https://git-scm.com/book/en/v2/Git-Tools-Submodules)
- [basic-memory](https://github.com/basicmachines-co/basic-memory)、[mcp-memory-service](https://github.com/doobidoo/mcp-memory-service)、[MCP memory server](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)
- [Notion Working with markdown content](https://developers.notion.com/guides/data-apis/working-with-markdown-content)、[飞书多维表格数据结构](https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-structure?lang=zh-CN)

---

## 3. 设计决策总览

| 决策点 | 结论 |
| --- | --- |
| 总体方案 | **方案 A：采纳标准 + 复用组件 + 薄自研层**（分 3 期） |
| 主存储 | **git + Markdown 为唯一事实源** |
| 跨项目共享 | **独立仓 `Agent-KB` + 各项目 git submodule 挂载** |
| 知识分层 | **双仓模型**：系统/通用层在 Agent-KB，项目层在各项目 `docs/kb/` |
| 条目粒度 | **原子化：一条知识 = 一个文件** |
| 元数据 | **YAML front-matter，`taxonomy.yaml` 为唯一事实源，schema 由此派生** |
| 协作工具 | 飞书/Notion **仅作单向只读镜像**（P2） |
| Agent 写入 | **草稿 + PR 人工审核门控**，Agent 不得直接产生 `accepted` |
| RAG | **不进 P0/P1**，仅当关键词检索命中率不足时按需叠加（P2 可选） |

---

## 4. 系统架构

### 4.1 五层架构

| 层 | 职责 | 存放位置 | 生成方式 |
| --- | --- | --- | --- |
| **L0 规范层** | 分类法、元数据 schema | `Agent-KB/taxonomy.yaml`、`schema/` | 手工维护 |
| **L1 内容层** | 知识条目（唯一事实源） | `Agent-KB/kb/**`（通用）+ 项目 `docs/kb/**`（项目级） | 手工 + Agent 草稿 |
| **L2 索引层** | 摘要索引 + 机器可读索引 | `INDEX.md`、`index.jsonl` | **脚本自动生成** |
| **L3 工具层** | `kb` CLI / MCP server | `Agent-KB/tools/` | 薄自研 |
| **L4 集成层** | 各项目入口 + submodule + 镜像 | 项目 `AGENTS.md`/`CLAUDE.md`、`integrations/` | P2 |

### 4.2 `Agent-KB` 仓库目录

```
Agent-KB/
├── AGENTS.md                       # Agent 唯一入口(≤200行), 只写"去哪找/怎么查", 不写知识正文
├── README.md                       # 面向人: 系统说明 + 贡献指南
├── taxonomy.yaml                   # 分类法唯一事实源
├── schema/
│   └── frontmatter.schema.json     # front-matter 的 JSON Schema(由 taxonomy 派生)
├── templates/                      # 知识模板
│   ├── decision.md  spec.md  plan.md  pitfall.md
│   ├── rca.md  howto.md  reference.md  retrospective.md
├── kb/                             # 通用/栈级知识(唯一事实源)
│   ├── INDEX.md                    # 摘要层索引(生成)
│   ├── index.jsonl                 # 机器可读索引(生成)
│   └── <type>/<domain>/<slug>.md
├── tools/kb/                       # CLI 实现
├── integrations/                   # P2: feishu-sync / notion-sync
└── docs/                           # 系统自身的 ADR 与说明(本文件所在)
```

### 4.3 双仓接入模型

```
<任意项目>/
├── .agent-kb/                      # git submodule, 挂载 Agent-KB(只读)
├── docs/
│   ├── kb/                         # 本项目知识(scope: project), 随代码版本化
│   │   ├── INDEX.md                # 生成
│   │   ├── index.jsonl             # 生成
│   │   └── <type>/<domain>/<slug>.md
│   └── ...
├── AGENTS.md                       # 指向两个索引 + 给出 kb 命令
└── CLAUDE.md                       # 精简: 引用 AGENTS.md
```

**设计理由**：知识与其代码库强耦合（某条踩坑是针对 v2.1 接口的），放到独立仓会导致"代码回滚/切分支时知识错位"。**通用/栈级知识**上提到 `Agent-KB` 实现真正跨项目复用；**项目级知识**留项目内随代码版本化。两者共用同一套 schema、模板、CLI、索引格式——**共享的是系统，不是所有内容**。

---

## 5. 分类标准

### 5.1 维度 A：`type`（知识类型）

| type | 中文 | 回答的问题 | 骨架来源 |
| --- | --- | --- | --- |
| `decision` | 技术决策 | 为什么选 A 不选 B | MADR / ADR |
| `spec` | 设计/需求规格 | 要做成什么样 | 现有 superpowers/specs |
| `plan` | 实施计划 | 分几步做、做到哪 | 现有 superpowers/plans |
| `pitfall` | 踩坑记录 | 踩了什么坑、怎么绕 | 现有 known-pitfalls |
| `rca` | 故障根因分析 | 线上为什么炸了 | Google SRE postmortem |
| `howto` | 操作指南 | 怎么做（可执行步骤） | Diátaxis how-to |
| `reference` | 参考资料/术语 | 这东西是什么 | Diátaxis reference |
| `retrospective` | 经验复盘 | 这个阶段学到了什么 | 项目复盘 |

> `pitfall` 与 `rca` 的区别：**pitfall** = 开发中踩到、影响面小、可自行绕过；**rca** = 已造成故障/影响面大、需时间线与行动项。同类问题开发期是 pitfall、上线后是 rca，用 `related` 关联。

### 5.2 维度 B：`domain`（领域/技术栈）

跨语言通用主域（可多值，允许在 `taxonomy.yaml` 登记自定义域）：

`backend`（后端）、`frontend`（前端）、`database`（数据库）、`devops`（基础设施/运维）、`security`（安全）、`testing`（测试）、`build`（构建/工具链）、`algorithm`（算法/模型）、`process`（研发流程）、`tooling`（协作工具）。

### 5.3 属性 1：`scope`（复用范围）

| scope | 含义 | 落位 |
| --- | --- | --- |
| `project` | 只对本项目成立 | 项目内 `docs/kb/` |
| `stack` | 对某技术栈通用 | `Agent-KB/kb/` |
| `universal` | 与栈无关的通用经验 | `Agent-KB/kb/` |

`kb lint` 校验：`scope != project` 的条目不应出现在项目仓，`scope == project` 的条目不应出现在 `Agent-KB`。

### 5.4 属性 2：`status`（生命周期，借 ADR 状态机）

`draft → proposed → accepted → deprecated / superseded`

- `draft`：Agent 生成的草稿，**不进检索索引**、不参与检索。
- `accepted`：人工/PR 审核通过，正式生效。
- `deprecated`：已过时但保留（附原因）。
- `superseded`：被新条目取代（必须填 `superseded_by`，双向可追）。

### 5.5 属性 3：`severity`（严重度，仅 `pitfall`/`rca`）

`low | medium | high | critical`

### 5.6 属性 4：`confidence`（可信度）

`verified | probable | speculative`

**对抗 AI 幻觉的关键**：Agent 生成且未验证的结论标 `speculative`；检索默认只信 `verified`/`probable`，`speculative` 降权。避免"AI 写的东西被当事实二次复用"污染知识库。

---

## 6. 元数据规范（front-matter）

### 6.1 字段定义

| 字段 | 必填 | 类型 | 取值/说明 |
| --- | --- | --- | --- |
| `id` | ✅ | string | 不可变短码 `kb-<yyyyMMdd>-<4hex>`，生成后不可改，引用与去重一律用 id |
| `title` | ✅ | string | 一句话说清，与文件内 H1 一致 |
| `type` | ✅ | string | 枚举见 §5.1 |
| `domain` | ✅ | string[] | 枚举见 §5.2，可多值 |
| `tags` | ❌ | string[] | 自由标签，检索加权 |
| `scope` | ✅ | string | `project` / `stack` / `universal` |
| `status` | ✅ | string | `draft` / `proposed` / `accepted` / `deprecated` / `superseded` |
| `severity` | 条件 | string | `pitfall`/`rca` 必填；`low`/`medium`/`high`/`critical` |
| `confidence` | ✅ | string | `verified` / `probable` / `speculative` |
| `created` | ✅ | date | `YYYY-MM-DD` |
| `updated` | ✅ | date | `YYYY-MM-DD` |
| `review_by` | ❌ | date | 时效性到期日，到期进入"待复核清单" |
| `source.project` | ❌ | string | 来源项目名 |
| `source.ref` | ❌ | string | PR / commit / issue 引用 |
| `related` | ❌ | string[] | 相关条目 id 列表 |
| `supersedes` | ❌ | string \| null | 取代的条目 id |
| `superseded_by` | ❌ | string \| null | 被谁取代 |

> 所有时间采用 `YYYY-MM-DD HH:mm:ss` 或 `YYYY-MM-DD` 格式（本体系元数据统一用 `YYYY-MM-DD`）。

### 6.2 示例

```yaml
---
id: kb-20261012-7f3a
title: Vite HMR 在 Windows 下不生效
type: pitfall
domain: [frontend, build]
tags: [vite, hmr, windows]
scope: stack
status: accepted
severity: medium
confidence: verified
created: 2026-10-12
updated: 2026-10-12
review_by: 2027-10-12
source:
  project: flysee-video-setting
  ref: "PR#42 / commit abc123"
related: [kb-20260901-11be]
supersedes: null
superseded_by: null
---
```

### 6.3 Schema 派生关系

`taxonomy.yaml` 是分类法唯一事实源 → `schema/frontmatter.schema.json` 由脚本生成 → `kb lint` 依赖 schema 校验。新增 domain/type 只改 `taxonomy.yaml` 一处，避免枚举不一致。

`taxonomy.yaml` 形态：

```yaml
version: 1
types:
  pitfall:
    label: 踩坑记录
    template: pitfall.md
    requires: [severity]
    sections: [背景/现象, 根因/决策, 解决方案/落地, 验证, 适用边界与反例, 参考]
  # decision / spec / plan / rca / howto / reference / retrospective 同理
domains:
  frontend: {label: 前端}
  backend:  {label: 后端}
  # ...
enums:
  scope:      [project, stack, universal]
  status:     [draft, proposed, accepted, deprecated, superseded]
  severity:   [low, medium, high, critical]
  confidence: [verified, probable, speculative]
```

---

## 7. 命名与路径规范

- **路径**：`kb/<type>/<domain>/<slug>.md`（目录名**直接取 `type` 枚举值本身**，单数、不做复数映射，保证机器可派生）
  例：`kb/pitfall/frontend/2026-10-12-vite-hmr-windows.md`
- **`<slug>`**：`YYYY-MM-DD-<kebab-case 短标题>`，人类友好、可改名。
- **`id`**：生成时分配的不可变短码 `kb-<yyyyMMdd>-<4hex>`；slug/路径可改而不断链。
- 文件内**只有一个 H1**，与 `title` 对应；**一条知识 = 一个文件**。

---

## 8. 模板规范

`templates/` 下每类一个模板文件，含"front-matter 骨架（带字段注释）+ 该 type 的正文骨架"。`kb new` 自动套用。

以 `pitfall.md` 为例（其余同理，按 type 裁剪正文骨架）：

```markdown
---
id: {auto}
title: {一句话说清问题}
type: pitfall
domain: []
tags: []
scope: project
status: draft
severity: medium
confidence: speculative
created: {auto}
updated: {auto}
---

# {title}

## 背景 / 现象
<!-- 什么场景、什么版本、触发条件、报错原文 -->

## 根因 / 决策
<!-- 真正的机制原因, 不要只写表象 -->

## 解决方案 / 落地
<!-- 具体改了什么; 命令/配置/代码 -->

## 验证
<!-- 如何确认已解决: 命令输出/复现步骤/数据 -->

## 适用边界与反例
<!-- 什么情况下这个结论不成立 -->

## 参考
<!-- 链接 / commit / issue -->
```

**正文统一六段式**（按 type 裁剪）：

| type | 正文骨架 |
| --- | --- |
| pitfall | 背景/现象 · 根因 · 解决方案 · 验证 · 适用边界与反例 · 参考 |
| rca | 现象 · 影响 · 时间线 · 根因 · 处置 · 预防 · 行动项 |
| decision | 背景 · 候选方案 · 决策 · 理由 · 后果 |
| howto | 前提 · 步骤 · 验证 · 常见错误 |
| spec / plan | 沿用现有 superpowers 模板，补齐 front-matter |
| reference | 定义 · 用法 · 示例 · 参考 |
| retrospective | 目标 · 结果 · 做得好的 · 待改进 · 行动项 |

---

## 9. 录入流程

### 9.1 人录入流程

```
kb new <type> --domain <d> --scope <s>   # 生成 draft(自动 id/日期/slug)
  → 填写 → kb lint                        # 本地校验
  → git commit → PR
  → 人工审核 → 合并
  → CI 自动 kb index                       # 重建 INDEX.md / index.jsonl
```

### 9.2 Agent 录入流程（自动沉淀闭环 + 门控）

```
任务结束/修复完成
  → kb search 查重
      ├─ 命中 → 更新既有条目（追加"新发现"）
      └─ 未命中 → kb new --generated
  → 填六段式；status=draft；confidence=speculative
  → 进 PR
  → 人工审核
      ├─ 通过 → status=accepted
      └─ 驳回 → 丢弃/修改
```

**Agent 门控红线（写进每个项目的 `AGENTS.md`，强制）：**

1. Agent **永远不能**直接写 `status: accepted`，只能产出 `draft`。
2. Agent **永远不能**写 `scope != project` 的条目，只能"建议提升到 Agent-KB"由人确认。
3. 沉淀前**必须**先 `kb search` 去重；命中则"更新"而非"新建"。
4. 无实测证据的结论**必须**标 `confidence: speculative`。
5. 单次任务最多沉淀 N 条（默认 3，防刷噪音）。

### 9.3 去重机制（三级）

| 级别 | 手段 | 触发时机 |
| --- | --- | --- |
| 一级 | 标题 + 标签模糊匹配（`kb search`） | Agent/人录入前 |
| 二级 | 内容指纹：对"根因"段规范化后取 hash 存 `dedup_key`，lint 检测冲突 | 提交时 |
| 三级 | 人工 review | PR 审核 |

---

## 10. 维护机制

| 机制 | 做法 |
| --- | --- |
| 索引自动同步 | pre-commit hook / CI 跑 `kb index`；CI 检测未同步则失败 |
| lint 校验 | schema、必填字段、枚举值、日期格式、id 唯一、`related/supersedes` 引用有效、链接可达 |
| 时效性 | `review_by` 到期进入"待复核清单"；每季度"知识体检" |
| 废弃治理 | `deprecated/superseded` + 原因 + 双向引用，索引中折叠展示 |
| 质量报告 | `kb stat`：各域条目数、draft 积压、待复核数、confidence 分布、最常被引用条目 |
| 反污染 | draft 不进检索索引；speculative 检索降权 |

---

## 11. AI 接口标准（token 适配）

### 11.1 渐进式披露三级

| 层级 | 载体 | 内容 | 加载时机 |
| --- | --- | --- | --- |
| L1 | 项目 `AGENTS.md`（≤200 行） | 只写"知识库在哪、怎么查、什么规则" | 常驻 |
| L2 | `INDEX.md` | 每行 `- [title](path) · type · domain · status · 一句话摘要` | 判断相关性时 |
| L3 | 单条 `.md` | 全文 | 确定相关后 |

### 11.2 CLI 命令（P0）

| 命令 | 作用 |
| --- | --- |
| `kb new <type> [--domain d] [--scope s] [--title t] [--generated]` | 生成新条目 |
| `kb lint [path]` | 校验 schema/枚举/引用/链接 |
| `kb index [--check]` | 重建（或检查）INDEX.md 与 index.jsonl |
| `kb search [--type][--domain][--tag][--scope][--status][--confidence][--query][--limit]` | 只返回元数据+摘要+路径，默认 limit 20 |
| `kb show <id>` | 单条全文 |
| `kb related <id>` | 反向链接 |
| `kb stat [--due-review]` | 质量报告 / 待复核清单 |
| `kb promote <id> --to <scope>` | 标记"建议提升到 Agent-KB"（供人决策） |

### 11.3 MCP 工具（P1）

`kb_search` / `kb_get` / `kb_create` / `kb_update` / `kb_related`，语义与 CLI 一致。对齐 Anthropic "Writing effective tools for agents"：工具面向**意图**而非端点 1:1 映射；返回 token 高效、默认分页与截断、约 25k token 上限。

### 11.4 `index.jsonl` 记录结构

```json
{"id":"kb-20261012-7f3a","title":"...","type":"pitfall","domain":["frontend"],
 "tags":["vite"],"scope":"stack","status":"accepted","severity":"medium",
 "confidence":"verified","path":"kb/pitfall/frontend/2026-10-12-vite-hmr.md",
 "summary":"...","dedup_key":"a1b2c3","related":[],"updated":"2026-10-12","repo":"agent-kb"}
```

- `summary` 从正文首段自动抽取。
- `draft` 条目写入单独 `index.draft.jsonl`，默认不参与检索。

---

## 12. 协作工具集成（P2，单向镜像）

- git 是唯一事实源；镜像**只读**，从根上避免双写冲突。
- **飞书**：Base 表存元数据（id/title/type/domain/status/severity/review_by）、docx 存正文，用 lark MCP 单向推送。
- **Notion**：官方 MCP / markdown API 推送页面。
- 同步脚本以 `id` 为幂等键 upsert，支持 `--dry-run`；人类意见走评论/PR，不直接改镜像。

---

## 13. 三期路线图

| 期 | 目标 | 交付 | 依赖 |
| --- | --- | --- | --- |
| **P0** | 骨架跑通 | Agent-KB 仓（taxonomy/schema/templates/tools/AGENTS.md）+ `kb` CLI（new/lint/index/search/show/stat）+ 各项目 submodule 接入 + 现有资产迁移 + pre-commit/CI | **零外部服务** |
| **P1** | 检索与门控闭环 | MCP server（复用 `basic-memory` 或自研薄 MCP）+ Agent 门控规则 + 去重指纹 | MCP 运行时 |
| **P2** | 协作镜像 + 可选 RAG | 飞书/Notion 单向镜像；命中率不足时再叠加向量检索 | SaaS 凭证 |

---

## 14. 与现有资产的衔接

| 现有资产 | 处理 |
| --- | --- |
| `docs/known-pitfalls/`（README + 主题聚合文件） | 拆分迁移为原子条目；涉及 flysee 具体接口/业务的 → `scope: project`（留项目内），纯技术栈通用的 → `scope: stack`（上提到 Agent-KB） |
| `docs/superpowers/specs`、`docs/superpowers/plans` | 迁入 `docs/kb/specs`、`docs/kb/plans`，补齐 front-matter |
| `CLAUDE.md` 中 known-pitfalls 大段规则 | 精简为一条"见 AGENTS.md" |

---

## 15. 风险与取舍

| 风险 | 缓解 |
| --- | --- |
| 原子化导致文件数激增 | 目录即分类；INDEX 按 domain 聚合；主题视图由脚本生成 |
| Agent 写入污染知识库 | 强制 draft + PR 门控 + 去重指纹 + confidence 标注 + 单次条数上限 |
| 上游组件（basic-memory 等）停更 | P0 不依赖任何外部组件；P1 才引入且为 MIT 许可，可自持 |
| 分类法过度设计 | taxonomy 由一个 yaml 驱动，可增删；P0 只落最小集合 |
| 双仓同步心智负担 | `kb init` 一键接入 + submodule 锁定版本 + CI 校验 |

---

## 16. 验收标准

1. `Agent-KB` 仓具备 taxonomy / schema / 模板 / CLI / AGENTS.md，`kb lint` 与 `kb index` 可运行且通过。
2. 至少一个项目完成 submodule 接入，`AGENTS.md` 指向两个索引，Agent 能按三级披露读取知识。
3. 现有 `known-pitfalls` 完成迁移，`scope` 判定正确（通用上提、项目留存）。
4. Agent 录入流程可跑通且门控生效：产出为 `draft`，进 PR 后由人工转 `accepted`。
5. 生成 `index.jsonl`，`kb search` 只返回元数据+摘要、不返回正文。

---

## 17. 待确认事项

无。本设计已通过分节评审（架构 / 分类 / 模板与流程 / 维护与接口），进入实现计划阶段。
