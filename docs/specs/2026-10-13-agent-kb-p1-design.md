# Agent-KB P1 设计 — 检索与门控闭环

- 日期: 2026-10-13
- 状态: 已评审通过 (2026-10-13, 分节评审: 架构与模块 / 闭环流程与验收)
- 上游: `docs/specs/2026-10-12-agent-kb-design.md` (总设计, 下称 P0 spec)
- 前置: P0 已完成 (Agent-KB @ 24584fa, flysee-video-setting feat/agent-kb-onboarding @ 1cf1a2d)

---

## 1. 背景与目标

P0 交付了 git + Markdown 事实源、taxonomy 派生 schema、`kb` CLI 8 命令、flysee 接入与 245 条迁移。遗留问题:

1. Agent 检索要靠人提醒去查两个仓 (项目 kb + Agent-KB), 易漏。
2. 写入门控只存在于 AGENTS.md 文字红线, 工具层无强制: CLI 可直接建任意 status/scope 条目, 无查重。
3. `dedup_key` 字段在 schema/index 中透传但无生成与冲突检测逻辑 (P0 spec §9.3 二级去重未落地)。
4. 245 条迁移条目全部标 `needs-scope-review`, scope 终审 deferred。
5. 终审 deferred 的工程 minors (pre-commit/CI/异常输出/可移植入口等)。

P1 目标: **检索与门控闭环** — MCP 工具面 + core 层强制门控 + 去重指纹 + scope 终审完成 + 工程收尾。

## 2. 范围

**In scope**
- core 新增 `dedup.py` (指纹) 与 `gate.py` (门控写入口), CLI 与 MCP 共用
- MCP server (官方 `mcp` SDK / FastMCP, stdio), 5 工具: `kb_search` / `kb_get` / `kb_related` / `kb_create` / `kb_update`
- 双层合并检索 (项目 kb + Agent-KB), MCP 默认, CLI 加 `--agent-kb` 开关
- 人工状态流转 `kb review`、scope 改判 `kb set-scope`、跨仓上提 `kb export`
- 245 条 needs-scope-review 终审 (分批提案 + 用户批次认定)
- 其余三仓接入 (flysee_video_web / flysee_video_algorithm / flysee_media_server)
- 工程 minors (见 §10)

**Out of scope (P2)**
- 飞书/Notion 单向镜像, RAG/向量检索, MCP HTTP 传输, 多团队 proposed 双阶审批流

## 3. 总体架构

**原则: 不变量在 core, 协议层无业务规则。**

```
┌─ CLI (cli.py) ─────────────────┐  ┌─ MCP server (mcp.py, 新增) ────────┐
│ kb new --generated (改走 gate)  │  │ kb_search / kb_get / kb_related     │
│ kb review / set-scope / export  │  │ kb_create / kb_update               │
│ (新增) kb stat --needs-scope    │  │ (stdio, 默认双层)                    │
└───────────────┬─────────────────┘  └───────────────┬─────────────────────┘
                ▼                                    ▼
      ┌──────────────────────────────────────────────────────┐
      │ core: gate.py(新) dedup.py(新) layers.py(新)          │
      │ 既有: new_entry / search / query / lint / index / ... │
      └──────────────────────────────────────────────────────┘
```

- **gate 是工具层强制, 非密码学强制**: Agent 仍可手改文件绕过, 由 AGENTS.md 红线 + PR review + lint 兜底。工具面保证的是"走正门必受控"。
- MCP 模块只做协议适配: 解析参数 → 调 core → 序列化。门控行为与 CLI 不可能漂移。

## 4. 去重指纹 (`src/kb/dedup.py`)

- `fingerprint(entry: Entry) -> str`:
  1. 取正文中第一个标题含 "根因" 的 H2 段全文 (pitfall / rca 均有); 该 type 无根因段则取正文全文 (去 H1)。
  2. 规范化: 转小写 → 删除所有空白 → 删除中英文标点 (集合固定写死在代码常量, 含 `，。、；：""''（）《》【】…—～` 及 ASCII 标点)。
  3. `sha256(规范化文本 utf-8).hexdigest()[:12]`。
- 指纹**不写入 front-matter**, 由 `kb index` 构建时现算写入 `index.jsonl` 的 `dedup_key` 字段 (避免正文改动后指纹漂移与双写不一致)。
- **偏离记录**: P0 spec §11.4 将 `dedup_key` 描述为条目字段; P1 改为索引期派生。schema `frontmatter.schema.json` 移除 `dedup_key` 属性, 本文件即为偏离备案。
- `kb lint` 新增规则: 同仓内两条目指纹相同 → error; 与对端仓 (存在 `--agent-kb` 或 `.agent-kb/` 时) 相同 → warning。存量 245 条 index 重建时自然回填, 冲突者进终审清单处理。

## 5. 门控 core (`src/kb/gate.py`)

### 5.1 `create_draft(repo, *, type, domain, title, body=None, tags=None, severity=None) -> Entry`

强制不变量 (参数无法覆盖):
- `status: draft`, `confidence: speculative`, `scope: project`
- 每次仅 1 条 (无批量接口)

流程:
1. 查重: 新条目指纹 vs 两层 `index.jsonl` 的 `dedup_key`; 标题分词 (小写, 按非字母数字切分取长度 ≥2 的 token, 取前 3 个) vs 两层检索。任一命中 → 抛 `DuplicateCandidate(entries=[...])`, 调用方 (MCP/CLI) 收到既有条目列表并拒绝新建。
2. 未命中 → 调 `new_entry.create_entry(repo, ..., generated=True)` 落盘; 给了 `body` 则整体替换模板正文, `tags`/`severity` 非空则写入。
3. 返回 Entry, 不自动重建 index (与 P0 CLI 行为一致, 由 pre-commit/CI 把关)。

### 5.2 `update_draft(repo, id, *, title=None, body=None, tags=None, severity=None) -> Entry`

- 目标条目必须存在于**本仓**且 `status == draft`, 否则抛 `GateViolation` (含实际 status)。
- 只更新显式提供的字段; 刷新 `updated`; `id/type/scope/status/confidence` 永不可经此路径改动。

### 5.3 `review(repo, id, to: str) -> Entry` (人工 CLI 专用, 不进 MCP)

合法流转表 (表外一律 `GateViolation`):

| from \ to | draft | proposed | accepted | deprecated | superseded |
|---|---|---|---|---|---|
| draft | — | ✓ | ✓ | ✓ | — |
| proposed | ✓ (打回) | — | ✓ | ✓ | — |
| accepted | — | — | — | ✓ | ✓ |
| deprecated / superseded | 终态, 不可回迁 (复活=新建条目并 related) ||||

- `to == accepted` 时校验: confidence 不得为 `speculative` (未核实的不能直接 accepted, 需先人工改 confidence 或降 draft)。

### 5.4 `set_scope(repo, id, scope) -> Entry`

- 改 `scope`, 并移除 `tags` 中的 `needs-scope-review` (终审执行手)。scope 值受 taxonomy 枚举约束。

### 5.5 `export_entry(project_repo, agent_kb_repo, id, *, to_scope) -> Path`

- 跨仓上提: 复制条目到 `<agent_kb>/kb/<type>/<domain>/<原文件名>` (文件名不变, 冲突则报错不覆盖), 置 `scope: to_scope` (限 stack/universal), 移除 `needs-scope-review`, 项目仓原文件删除 (git 记录 rename, id 不变)。
- 目标仓同 id 已存在 → 报错。完成后提示两仓各跑 `kb index`。

### 5.6 对 P0 代码的改动

- `cli.py` `kb new --generated` 改走 `gate.create_draft`; 非 generated (人工) 路径保持直连 `create_entry`。
- `taxonomy.derive_schema` 移除 `dedup_key`; `index.py` 改为 `fingerprint()` 现算。

## 6. MCP server (`src/kb/mcp.py`)

- 官方 `mcp` Python SDK (FastMCP), **stdio** 传输。依赖走 extras: `pip install -e .agent-kb[mcp]`, core CLI 保持零新增依赖。
- 启动 (各项目 MCP 配置): `python -m kb.mcp --repo docs --agent-kb .agent-kb`。`--agent-kb` 可省略 (则单层)。`--repo-name` 自定义项目层在返回 `repo` 字段中的标注名 (默认取 `--repo` 目录名, 同 CLI index)。
- 所有工具异常统一捕获: 返回 tool error (`isError=true` + 单行可读消息), 不抛 traceback。

| 工具 | 参数 | 行为 |
|---|---|---|
| `kb_search` | query?, type?, domain?, tag?, scope?, limit=10 | 双层合并: 项目层命中在前, Agent-KB 层在后, 总截断 limit。只返元数据+summary+path+repo, 不含正文; draft 不出现 (只读各层 index.jsonl) |
| `kb_get` | id | 跨两层按 id 取全文 markdown; 两层同 id 时项目层优先并在结果中注明; 未命中返回 not found |
| `kb_related` | id | 语义同 CLI `kb related`, 双层各查合并 |
| `kb_create` | type, domain, title, body, tags?, severity? | → `gate.create_draft`; 查重命中时返回既有候选列表 + "请改用 kb_update" 提示 |
| `kb_update` | id, title?, body?, tags?, severity? | → `gate.update_draft`; 非 draft / 跨仓 id 一律拒绝 |

Token 约束 (对齐 P0 spec §11.3): search 默认 limit 10; 单条原子条目全文天然有界; 返回均为紧凑 JSON。

## 7. 双层检索 (`src/kb/layers.py`)

- `search_layers(repos: list[Path], **filters)` / `get_layered(repos, id)` / `related_layers(repos, id)`: 顺序即优先级, 逐层调既有单仓函数, 合并加 `repo` 标注, 截断。
- CLI `kb search / show / related` 新增 `--agent-kb <path>` (可多次), 给出即双层, 与 MCP 共用 layers。

## 8. CLI 变更汇总

| 命令 | 变更 |
|---|---|
| `kb new` | `--generated` 走 gate; `--scope` 加 `choices=[project,stack,universal]`; 新增 `--body-file` (draft 正文一次写入) |
| `kb review <id> --to <status>` | 新增, §5.3 |
| `kb set-scope <id> <scope>` | 新增, §5.4 |
| `kb export <id> --to-repo <agent-kb-path> --to-scope <scope>` | 新增, §5.5 |
| `kb stat --needs-scope [--format json\|md]` | 新增: 列 `needs-scope-review` 条目 (id/标题/domain/summary), md 格式供批次提案表格 |
| `kb search/show/related` | 加 `--agent-kb` (可多次) 启用双层 |
| `kb lint` | 加 §4 指纹查重规则; 加 `--agent-kb` (可多次) 做跨仓 warning |
| `kb index` | dedup_key 现算 (§4) |
| 全局 | `main()` 外层 try/except: 预期异常 (GateViolation/DuplicateCandidate/ValueError) 输出单行 `kb error: <msg>` 到 stderr, exit 1; 未预期异常保留 traceback 便于报障 |

## 9. 245 条 scope 终审工作流

1. `kb stat --needs-scope --format md` 生成全量清单。
2. 按 domain 分 4 批: database (9) → frontend (85) → backend A (78) → backend B (73)。
3. 每批: Agent 输出建议表 (`id / 标题 / 建议 scope / 一句话理由`), 用户批次认定 (可整批通过或逐条改判)。
4. 执行: 留存条目 `kb set-scope <id> project`; 上提条目 `kb export ... --to-scope stack|universal`; 每批完成后两仓 `kb index` + `kb lint` (含跨仓指纹 warning 复核)。
5. 判定标准 (写入项目 AGENTS.md): 换仓库即失效/含项目接口或业务语义 → project; 技术栈通用、经人确认可复用 → stack; 与栈无关的流程/方法论 → universal。
6. 验收: `kb stat --needs-scope` 计数为 0。

## 10. 工程 minors (P0 deferred 清零)

| 项 | 处理 |
|---|---|
| pre-commit hook 依赖 PATH 上的 `kb` | 改 `language: system` + `python -m kb.cli lint`, 或 venv 路径, 以实际可用为准 |
| CI push+PR 双触发; 无 pip 缓存 | 触发只留 `pull_request` + `push: [master]`; `setup-python` 加 `cache: pip` |
| `kb new --scope` 无枚举校验 | §8 choices |
| AGENTS.md 命令入口硬编码绝对路径 | 改为项目根相对写法: `.agent-kb/.venv/Scripts/python.exe -m kb.cli --repo docs` (Windows) 与 `.agent-kb/.venv/bin/python` (POSIX) 两行 |
| schema 漂移无测试 | 加测试: `derive_schema(load_taxonomy())` == 已提交 `frontmatter.schema.json` (加载后结构比较) |
| flysee `docs/backlog/` 未跟踪目录 | 与本体系无关, 提请用户自行处置 (不入库) |

## 11. 其余三仓接入

每仓流程 = 摸底 (`Glob` 其文档目录判定有无成体系 pitfalls/specs) → `.agent-kb` submodule + `docs/kb/` 骨架 + `AGENTS.md` 入口 + lint/index 跑通 → 有存量则按 flysee 迁移模式分批迁移。无成体系文档的仓只接入口。

## 12. 测试与验收

**测试 (TDD, 预计新增 ~35 例)**
- dedup: 规范化边界 (中英标点/空白/大小写)、根因段提取、无根因段类型退化全文、12hex 稳定
- gate: 拒绝矩阵 (非 draft 的 update / 非法 status 初值不可能 / 流转表外 review / accepted 时 speculative 拒绝 / 查重两类命中)
- layers: 顺序优先级、同 id 项目层优先、limit 截断
- export: 复制+改 scope+去标签+源删除、目标冲突报错
- index/lint: dedup_key 现算、同仓冲突 error、跨仓 warning
- MCP: in-memory client 端到端 5 工具, 含门控拒绝与查重返回体
- schema 漂移测试 (§10)

**验收标准**
1. flysee 配好 MCP 后, 真实 Agent 会话可完成 "查→沉淀 draft→人工 review accepted" 全闭环。
2. 门控不可经工具面绕过: MCP/CLI 任何路径不能由 Agent 直接产出非 draft/非 project 条目; 查重命中必拒建。
3. 245 条 `needs-scope-review` 清零, 上提条目在 Agent-KB 仓 lint/index 绿。
4. 其余三仓接入完成, 四仓 (含 flysee-video-setting) lint / index --check / CI 全绿; Agent-KB 测试套件 (44 + 新增) 全绿。
5. P0 deferred minors 全部关闭 (§10 表逐项勾验)。

## 13. 风险与取舍

| 风险 | 缓解 |
|---|---|
| 查重依赖 index 新鲜度 (忘跑 index 会漏检) | pre-commit 强制 `index --check` + lint 冲突兜底 |
| 指纹过严漏检 / 过松误报 | 只做规范化精确匹配, 不做模糊相似 (误报靠 lint warning 可见, 漏报由标题 token 查重补) |
| mcp SDK 版本演进 | 锁 minor 版本下限, extras 隔离, core 不受影响 |
| 跨仓 export 破坏 git 历史直觉 | export 单命令完成双侧改动并提示 index; id 不变保证引用稳定 |
| MCP 本机 stdio 无鉴权 | 与 CLI 同信任域 (本机开发者), 不引入 token 机制 (YAGNI) |
