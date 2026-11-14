# Agent-KB ↔ RepoWiki 双向桥 设计文档

日期：2026-11-14
状态：已确认（设计评审通过，待写实施计划）
实施仓库：Agent-KB（`src/kb/`）

## 1. 背景

Qoder（IDE/CLI）的 RepoWiki 功能由云端分析管线生成项目模块文档：先规划模块
划分（可被 `.qoder/repowiki/wiki_plan.yaml` 干预），再由默认模型逐模块生成五类
知识卡（概述 / 架构设计 / 技术栈 / 编码规范 / 特殊配置与命令），并可持续增量更新。
生成结果存服务端，可通过"导出到 `.qoder/repowiki`"落盘为文件格式随 Git 共享，
也可"导入自 `.qoder/repowiki`"回读（语义为**替换**当前对应内容）。

导出格式（本机 `.qoder/repowiki/knowledge/zh/` 实例已解析）：

- `_index.yaml`：模块树（`module_path` → `dir_name`/`title`/`scope`/`children`/
  `depends_on`/`related_to`/`version_of`）+ `commit`/`branch`/`exported_at`
- 每模块一个目录 + `_module.yaml`（含 `kk_module_id`、`kk_cards` 各卡 UUID/id/title）
- 卡正文为纯 markdown；仓库级卡（`build_system`/`dependency_management`/
  `error_handling`/`logging_system`/`frontend_style`）平铺在根模块目录

其卡片类型枚举与 Agent-KB 检索分类（SearchKnowledge category 后缀）几乎重合，
说明两者建模同一层概念，只是粒度不同：repowiki 卡是"模块文档"，Agent-KB 条目是
"经验原子"（pitfall/rca/howto…，带 status/confidence 门控）。

## 2. 目标与非目标

**目标**

1. Agent-KB（事实源）可投影为 RepoWiki 文件格式：`kb repowiki export` 把项目库
   条目按模块聚合进五类卡，输出 `.qoder/repowiki/knowledge/zh/` 完整结构，
   Qoder 可导入消费。
2. RepoWiki 产物可被 kb 检索穿透：`kb index` 把目标仓 `.qoder/repowiki` 纳入
   L2 侧车索引，`kb search` 三层命中，`kb show` 读原文。

**覆盖语义（导出器为叠加/覆盖式 overlay）**：导出器只写它管理的两类模块卡
（`architecture_design`、`unique_setup_and_commands`），不触碰 Qoder 原生卡；
读取已有 `_index.yaml`/`_module.yaml` 时保留原生模块树与原生卡 UUID。

**非目标**

- 不替代 Qoder 原生 wiki 生成管线；导出器只写 kb 投影内容。
- 不把 repowiki 卡转成 kb 实体条目（避免冲击查重/门控体系）。
- 不依赖 Qoder 在线；桥的全部功能离线可用。
- 第一版不聚合仓库级卡（`build_system` 等）。

## 3. 架构

新增子系统 `kb.repowiki`，两个交付面：

```
docs/kb/ 条目(index.jsonl + 正文)                .qoder/repowiki/knowledge/zh/
      │                                                │
      │  ① kb repowiki export (投影, 幂等可重建)        │  ② kb index 探测
      ▼                                                ▼
.qoder/repowiki/knowledge/zh/              index.repowiki.jsonl (L2 侧车索引)
 _index.yaml + _module.yaml + 五类卡                    │
      │                                                ▼
      │                            kb search: project kb → repowiki → agent-kb
      └──(Qoder IDE "导入自 .qoder/repowiki"; 语义=替换, 见 §6)
```

## 4. 导出器 `kb repowiki export`

CLI：`kb repowiki export --repo docs [--lang zh] [--out <path>] [--modules <yaml>] [--write]`

- `--repo docs` 同既有约定；`--out` 默认 `<项目根>/.qoder/repowiki`。
- **默认 `--dry-run`**：只打印将写入的文件清单与每卡条目数；显式 `--write` 才落盘。

### 4.1 模块归属

- 条目 front-matter 新增**可选**字段 `module: <module_path>`；schema
  （`schema/frontmatter.schema.json`）与 `kb lint` 同步放行，缺省即"不导出"。
- 模块树来源优先级：
  1. 目标仓已有 `.qoder/repowiki/knowledge/<lang>/_index.yaml`（借 Qoder 原生模块划分，
     overlay 模式：保留原生模块树与原生卡 UUID，仅注入/更新 managed 卡）；
  2. `--modules <yaml>` 人工清单（同构 `modules:` 段，从零生成骨架：只写 managed 卡
     与 `_index.yaml`/`_module.yaml`，不生成无条目归属的原生卡文件）；
  3. 两者皆无 → 报错退出，提示先跑 Qoder 生成或提供 `--modules`。

### 4.2 卡内容=条目投影

不搬全文，保持 kb 为唯一事实源，避免双份漂移。每卡内按 type 分节：

```markdown
## 已知陷阱 (pitfall)
- **<标题>** — <一句话摘要>（kb id）

## 根因分析 (rca)
- ...
```

"一句话摘要"取主 `index.jsonl` 中该条目的 summary 字段（索引生成器已写入），
不重新解析正文。

卡枚举 → 文件名映射（全文固定）：

| card 枚举 | 文件名 |
| --- | --- |
| overview | 概述.md |
| architecture_design | 架构设计.md |
| tech_stack | 技术栈.md |
| coding_conventions | 编码规范.md |
| unique_setup_and_commands | 特殊配置与命令.md |

### 4.3 默认 type→卡映射（可用配置覆盖）

| 条目 type | 目标卡 |
| --- | --- |
| howto / reference | 特殊配置与命令 (`unique_setup_and_commands`) |
| decision / spec / plan / retrospective / rca / pitfall | 架构设计 (`architecture_design`) |
| —（overview / 技术栈 / 编码规范） | 不聚合条目，不生成/覆盖 |

映射可在 `docs/kb/repowiki.yaml` 的 `map:` 段按 type 覆盖。

### 4.4 UUID 策略

`kk_module_id` 与各卡 id 用 UUID5 确定性生成
（namespace = 固定常量 + module_path + 卡名），同输入幂等重建。
`commit`/`branch`/`exported_at` 取自目标仓当前 git 状态。

### 4.5 覆盖保护

managed 卡（`architecture_design`/`unique_setup_and_commands`）落盘前做指纹
检查：若该卡文件已存在且其中无任何本工具确定性 UUID/分节标记，视为外部内容，
打印警告："导入即替换，该卡当前内容将被 kb 投影覆盖"，需 `--force` 才继续；
卡内已有本工具标记则直接幂等重写。其余文件（原生卡、Qoder 管理的字段）一律不写。

## 5. 检索穿透

### 5.1 L2 侧车索引

`kb index --repo docs` 时探测 `<repo>/.qoder/repowiki/knowledge/*/`，解析
`_index.yaml` + `_module.yaml` + 卡文件首句，生成 `index.repowiki.jsonl`
（与主 `index.jsonl` 并列的**侧车文件**，不并入，不污染既有消费方）：

```json
{"kind": "repowiki_card", "module_path": "...", "card": "architecture_design",
 "title": "...", "summary": "<首句>", "path": ".qoder/repowiki/knowledge/zh/...md",
 "locale": "zh"}
```

### 5.2 三层检索

`kb search` 查询顺序：project kb → repowiki 侧车 → agent-kb；结果带
`kind` 字段区分来源。L3 经 `kb show --repowiki <module_path>/<card>`（或 MCP
`kb_get`）直接读卡原文。MCP `kb_search` 返回结构同步带 `kind`。

### 5.3 容错

- repowiki 目录缺失 = 静默跳过（非错误）。
- `_index.yaml` 解析失败或 `schema_version > 1` = 警告并跳过该语言目录
  （Qoder 格式漂移守卫）。

## 6. 风险与验证

| 风险 | 缓解 |
| --- | --- |
| **Qoder 导入对自造 UUID（`kk_module_id`/卡 id）的容忍度未知**（官方文档未说明按 ID 还是按结构匹配） | 导出器第一版落地后立刻真机实测；若不容忍，降级为"文件格式兼容 + Qoder 任务直接读文件"，文档标注限制 |
| 导入语义=**替换当前对应内容**；本工具仅写两类 managed 卡，原生卡不受写影响，但 Qoder 侧导入的替换粒度未知（可能整模块替换） | spec 与本节明示；managed 卡覆盖前警告 + `--force` 门；实测时确认替换粒度并回填本文档 |
| Qoder 格式漂移 | `schema_version` 守卫（§5.3） |

## 7. 测试

- **导出 roundtrip**：以 flysee-video-setting `docs/kb/` 真实条目做快照比对
  （`_index.yaml`/`_module.yaml`/managed 卡 md）；UUID 确定性（同输入两次导出完全
  一致）；overlay 模式保留原生卡 UUID 与文件不被触碰；默认 dry-run；
  外部内容卡拒绝 `--write`、`--force` 放行。
- **覆盖保护**：非本工具生成内容存在时拒绝 `--write`，`--force` 放行。
- **穿透**：fixture repowiki 目录的 sidecar 生成、`kb search` 三层命中与
  `kind` 区分、`kb show --repowiki` 读原文、缺失目录静默跳过、
  `schema_version` 守卫。
- **schema**：`module` 字段 lint 通过/拒绝用例；未归属条目计数警告。

## 8. 交付顺序

1. 导出器（含 UUID 实测，验证最大未知项）
2. 检索穿透（sidecar + 三层 search + L3 读原文）
3. 文档：`README` 增"RepoWiki 桥"一节，AGENTS.md 四仓同步一句话入口
