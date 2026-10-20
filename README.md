# Agent-KB

跨项目研发知识库系统: **git + Markdown 为唯一事实源**, 面向人 + AI Agent 双消费。
沉淀开发全流程知识(设计规格、技术方案、踩坑记录、故障根因、操作指南、经验复盘),
配套 `kb` CLI 做录入、校验、索引与检索。设计全文见
[`docs/specs/2026-10-12-agent-kb-design.md`](docs/specs/2026-10-12-agent-kb-design.md)。

## 系统定位

- **专业性**: 分类法(`taxonomy.yaml`)+ 结构化模板 + 质量门控(lint + PR 人工审核)。
- **规范性**: 统一 YAML front-matter 契约, 机器可校验(JSON Schema 派生自 taxonomy)。
- **可复用性**: 通用知识与项目知识分层, 一套系统服务所有项目。
- **低 token**: 三级渐进披露(AGENTS.md → INDEX.md → 单条全文), Agent 按需加载。

## 双仓模型

**共享的是系统(schema/模板/CLI/索引格式), 不是所有内容。** 项目级知识随代码版本化,
避免"代码回滚/切分支时知识错位"; 通用/栈级知识上提到本仓, 实现跨项目复用。

```
Agent-KB/                           # 本仓: 系统 + 通用知识
├── AGENTS.md                       # Agent 唯一入口(≤200行), 只写"去哪找/怎么查"
├── README.md                       # 本文件: 面向人的系统说明 + 贡献指南
├── taxonomy.yaml                   # 分类法唯一事实源
├── schema/
│   └── frontmatter.schema.json     # front-matter 的 JSON Schema(由 taxonomy 派生)
├── templates/                      # 8 类知识模板(kb new 自动套用)
├── kb/                             # 通用/栈级知识(scope: stack/universal)
│   ├── INDEX.md                    # 摘要层索引(kb index 生成, 勿手改)
│   ├── index.jsonl                 # 机器可读索引(生成)
│   ├── index.draft.jsonl           # draft 条目索引(生成, 不进正式检索)
│   └── <type>/<domain>/<slug>.md
├── src/kb/                         # CLI 实现(入口: kb)
└── docs/                           # 系统自身的 specs/plans
```

```
<任意项目>/                         # 接入侧
├── .agent-kb/                      # git submodule, 挂载 Agent-KB(只读)
├── docs/
│   └── kb/                         # 本项目知识(scope: project), 随代码版本化
│       ├── INDEX.md                # 生成
│       ├── index.jsonl             # 生成
│       ├── index.draft.jsonl       # 生成
│       └── <type>/<domain>/<slug>.md
├── AGENTS.md                       # 指向两个索引 + 给出 kb 命令
└── CLAUDE.md                       # 精简: 引用 AGENTS.md
```

## 安装

要求 Python 3.10+。在本仓根目录:

```powershell
pip install -e ".[dev]"     # 安装 kb 命令 + pytest 开发依赖
kb --help
```

## 快速上手

```powershell
# 1. 生成 proposed 条目(人类贡献默认 proposed; 自动分配 id/日期/slug, 自动套用模板)
kb new pitfall --domain frontend --scope project --title "Vite HMR 在 Windows 下不生效" --repo .

# 2. 按模板六段式填写正文(背景/现象 · 根因 · 解决方案 · 验证 · 适用边界与反例 · 参考)

# 3. 本地校验(schema/枚举/必填/引用/唯一 H1)
kb lint --scope project --repo .

# 4. 提交 PR, 人工审核通过后 status 转 accepted, CI 自动 `kb index` 重建索引
```

查询已有知识: `kb search --query "关键词" --repo .`(只返回元数据+摘要),
命中后 `kb show <id> --repo .` 读全文。

## 接入新仓(Quickstart, 三步)

前提: 本机已按同级克隆约定放置 Agent-KB 主仓并装好 venv(与业务仓同一父目录;
`kb init` 依赖此约定定位解释器)。

```powershell
# ① clone 业务仓后, 在业务仓根生成 .mcp.json(相对路径, 跨机可移植):
#    kb_dir 不存在时自动创建骨架, 未挂 submodule 时自动降级为单层配置
<Agent-KB>\.venv\Scripts\python.exe -m kb.cli init --repo docs --kb-dir docs

# ② 自检: venv/门禁依赖/index/lint/已装钩子/.mcp.json 可执行性, FAIL 才退 1
<Agent-KB>\.venv\Scripts\python.exe -m kb.cli doctor --repo docs

# ③ 重载 Agent 的 MCP 配置(重启会话), 即得 kb_search/kb_get/kb_create 工具面
```

可选(获得双层检索与通用知识库):

```powershell
git submodule add <Agent-KB-url> .agent-kb   # 挂只读 submodule
# 重跑 init --force + doctor, 即变双层(project 优先 + stack/universal)
powershell -File <Agent-KB>\scripts\install-gate.ps1 -RepoRoot .   # 装 push 门禁
```

## 审核与流转命令(人用)

```powershell
kb review <id> --to proposed --repo docs    # draft→proposed→accepted(speculative 被门禁拒)
kb review <id> --to accepted --evidence "实测证据出处" --repo docs   # accepted 时留痕 verification.evidence
kb set-scope <id> stack --repo docs         # scope 终审落地(清 needs-scope-review 标签)
kb export <id> --to-repo ../Agent-KB --to-scope stack --repo docs   # 项目库→通用库跨仓上提
```

## 观测面板(kb serve / kb web)

检索埋点默认开启(`kb init` 生成的 `.mcp.json` 带 `KB_TRACE=1`), 事件按日追加到
本仓 `traces/YYYY-MM-DD.jsonl`(入 git, 只含元数据+摘要级信息, 永不写正文)。
观测读侧与检索写侧彻底解耦: serve 挂了 trace 照常落盘, 不影响检索与门禁。

```powershell
kb web                                        # 打开观测面板(无 serve 时静默代拉起, 空闲自杀)
kb serve [--port 4320] [--bind 0.0.0.0 --token <令牌>]   # 观测服务端(只读 REST+SSE)
kb serve --install-autostart                  # 团队常开: 注册登录自启(Windows 计划任务/systemd 用户 unit)
kb spider-live                                # 检索事件实时直播到 prompt-spider-ui(需 Node 20+)
kb trace list --zero-hit / show <id> / export --latest   # 命令行查 trace / 导出蜘蛛回放
kb trace report                               # 零命中周报(高频待消化词+消化率; 每周一自动跑)
```

常用开关: `KB_TRACE=0` 关闭埋点; `KB_SOURCES=tdbm`(逗号分隔)启用外接知识源连接器;
`KB_SERVE_TOKEN` / `KB_INGEST_URL` 团队态令牌与上报口。指标口径唯一实现 serve,
面板只做展示; 命中率/零命中榜的改进回路是 `kb trace report`(见 PRD FR-3.5)。

### 团队常开态与令牌分发(PRD FR-2.5)

单人态开箱即用(仅 127.0.0.1, 无鉴权, 本机即边界); 团队态是配置升级而非架构切换。
`--bind` 非本机且无令牌 → serve **拒绝启动**(红线)。标准四步:

```
① 常开主机:  kb serve --bind 0.0.0.0 --port 4320 --token <随机 32 位> --install-autostart
             (令牌也可 setx KB_SERVE_TOKEN 注入, autostart 任务不落盘令牌)
② 成员机:    kb init --repo docs --serve-url http://kb.internal:4320 --token <令牌>
             → 落盘用户级 ~/.kb/config.toml(不入库): [serve] url/token
③ 业务仓 .mcp.json(入库安全, 只有地址无凭据): env 加 KB_TRACE=1、KB_INGEST_URL;
             上报令牌不进项目仓, 埋点从 ~/.kb/config.toml 读
④ 成员浏览器: kb web → 发现链读 config.toml 连团队实例; 不可达则降级本机+横幅明示
```

git 始终是权威账本, ingest 上报只是直播加速通道(幂等按 trace_id 去重)。

### 安全预案(触发前零改动, PRD v1.4 §7.3)

- **要对外网可见**: 前置反代 + TLS, 按新 FR 立项(现仅 127.0.0.1 / 内网 bind+单令牌)。
- **要多团队**: 优先双令牌重叠期轮换(serve 并行校验新旧两把), 或每团队独立 serve。
- **traces/ 年增长 >50MB**: 触发月分卷评审; **>20 人或 ≥2 仓同连一把 serve**: 触发小规模压测。

### trace 提交节奏(D-3 约定)

`traces/` 随检索不断变脏, 约定**每日定时任务自动提交**(每天 18:30, 只 commit 不
push, 推送仍人工): 平时不必手动提交 traces/, 也不必为它改 pre-push 钩子; 功能提交
时看到 traces/ 脏属预期, 跳过即可。周报/日报类自动化见 `docs/reports/`。

## 贡献流程

1. **查重先行**: 新建前 `kb search` 确认没有重复条目; 命中则更新既有条目而非新建。
2. **kb new** 生成 proposed 条目(Agent 草稿用 `--generated` 产出 draft) → 填写正文 →
   `kb lint` 通过 → `kb index` 刷新索引。
3. **PR + 人工审核**: 审核人把关收录标准与 scope 判定, 通过后改 `status: accepted`。
4. **scope 判定**: 项目内条目若具普适性, 用 `kb promote <id> --to stack` 标记建议,
   由人确认后迁移到本仓 `kb/`。
5. **生命周期**: `draft → proposed → accepted → deprecated/superseded`;
   被取代必须填 `superseded_by`, 过时条目可 `kb stat --due-review` 跟踪复核。

收录标准与 Agent 门控红线(仅 draft、不越权改 scope、先查重、无实测标 speculative、
单次最多 3 条)详见 [`AGENTS.md`](AGENTS.md)。

## 目录结构说明

| 路径 | 内容 | 维护方式 |
| --- | --- | --- |
| `taxonomy.yaml` | type/domain/scope/status 等全部枚举与正文骨架 | 手工, 唯一事实源 |
| `schema/frontmatter.schema.json` | front-matter 校验规则 | 由 taxonomy 派生 |
| `templates/` | decision/spec/plan/pitfall/rca/howto/reference/retrospective 模板 | 手工 |
| `kb/` | 通用/栈级知识条目(一条 = 一个文件) | 人 + Agent 草稿, PR 门控 |
| `kb/INDEX.md` `kb/index.jsonl` `kb/index.draft.jsonl` | 人读摘要索引 + 机器可读索引(含 draft) | `kb index` 生成 |
| `src/kb/` | `kb` CLI(new/lint/index/search/show/related/stat/promote) | 手工 |
| `tests/` | pytest 测试 | 手工 |
