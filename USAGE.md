# Agent-KB 使用手册

面向日常使用者的操作手册: **装什么 → 怎么查 → 怎么沉淀 → 怎么接入新项目 → 怎么看观测面板**。
系统定位、双仓模型与设计动机见 [`README.md`](README.md); Agent 侧的门控红线见
[`AGENTS.md`](AGENTS.md)。本文所有命令与参数均对齐 `src/kb/cli.py` 的实际实现。

## 1. 安装

要求 Python 3.10+。二选一:

```powershell
# 方式 A: venv + pip(推荐, 与 .mcp.json 的解释器约定一致)
cd <Agent-KB>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"      # MCP 面再加 ".[dev,mcp]"

# 方式 B: uv
uv venv && uv pip install -e ".[dev,mcp]" --python .venv\Scripts\python.exe
```

验证: `kb --help`、`kb doctor --repo .`(全绿或只剩可选 WARN 即就绪)。

包名 `agent-kb`, 控制台命令 `kb`(= `kb.cli:main`)。未装到 PATH 时用
`.venv\Scripts\python.exe -m kb.cli` 等价替代。

## 2. `--repo` 的口径(最容易踩的一条)

所有子命令的 `--repo` 指的都是**kb 载体目录**(其下有 `kb/`), 不是"git 仓根":

| 你在哪 | `--repo` 传什么 |
| --- | --- |
| Agent-KB 仓自身 | `--repo .`, 且 lint 用 `--scope agent-kb` |
| 业务仓(知识在 `docs/kb/`) | `--repo docs` |
| 通用知识层(submodule) | `--repo .agent-kb` |

`--agent-kb <路径>` 可重复, 用来叠加通用知识层做双层检索(project 优先)。

## 3. 日常检索(三级披露)

```powershell
kb search --query "vite hmr" --repo docs                    # L2: 只回元数据+摘要+路径
kb search --query "hmr" --type pitfall --domain frontend --confidence verified --repo docs
kb show kb-20261012-7f3a --repo docs                        # L3: 命中后才读全文
kb related kb-20261012-7f3a --repo docs                     # 反向链接
kb search --query "x" --repo docs --agent-kb .agent-kb      # 双层检索
```

筛选参数: `--type/--domain/--tag/--scope/--status/--confidence/--limit`(默认 20)。
`status: draft` 的条目不进检索索引; 单次检索默认落一条 trace(见 §7)。
本次不想留痕加 `--no-trace`, 强制留痕加 `--trace`。

## 4. 写一条新知识

```powershell
# ① 查重(强制): 命中就更新既有条目, 不要新建
kb search --query "拟写主题的关键词" --repo docs

# ② 生成骨架(自动分配 id/日期/slug, 自动套用模板)
kb new pitfall --domain frontend --scope project --title "Vite HMR 在 Windows 下不生效" --repo docs
#   pitfall/rca 可加 --severity low|medium|high|critical(默认 medium)
#   Agent 自动沉淀加 --generated → 强制 draft + speculative + scope=project

# ③ 按模板六段式补正文(一条 = 一个文件 = 一个 H1)

# ④ 校验 + 重建索引
kb lint --scope project --repo docs
kb index --repo docs
```

`<type>` ∈ decision / spec / plan / pitfall / rca / howto / reference / retrospective;
`--domain` ∈ backend / frontend / database / devops / security / testing / build /
algorithm / process / tooling。枚举唯一事实源是 `taxonomy.yaml`。

落盘路径固定为 `<kb载体>/kb/<type>/<domain>/<YYYY-MM-DD-slug>.md`; id 不可变, slug
可改不断链。`INDEX.md` / `index.jsonl` / `index.draft.jsonl` 是生成物, 永远 `kb index`
重建而非手改。

## 5. 状态流转与 scope 上提

生命周期: `draft → proposed → accepted → deprecated / superseded`(被取代必须填
`superseded_by`)。

```powershell
# 人工流转
kb review <id> --to proposed --repo docs
kb review <id> --to accepted --evidence "实测证据出处" --repo docs   # accepted 必须有 evidence

# Agent 自审(工具面允许, 全程留痕: auto-reviewed 标签 + verified_by: agent)
kb review <id> --to accepted --as-agent --confidence verified --evidence "实测证据出处" --repo docs

# 质量与待办
kb stat --repo docs                      # 质量报告(JSON)
kb stat --format md --repo docs          # 人读版
kb stat --due-review --repo docs         # 到期待复核
kb stat --needs-scope --repo docs        # 待判定 scope

# scope 上提: Agent 只能"建议", 落地必须人工
kb promote <id> --to stack --repo docs                                  # 只打建议标记
kb set-scope <id> stack --repo docs                                     # 终审落地(仓内改 scope)
kb export <id> --to-repo ../Agent-KB --to-scope stack --repo docs       # 跨仓搬进通用库
```

Agent 侧硬约束(由 `kb new --generated` / MCP 强制, 违规直接报错): 只能产 draft;
accepted 必须同时给 `evidence` 并把 confidence 提升到 verified/probable(speculative
永不 accepted); 永不改 scope; 单会话 accepted 最多 3 条。

## 6. 校验与索引细节

```powershell
kb lint --scope project --repo docs --strict            # warning 视为硬错误
kb lint --scope project --repo docs --update-baseline   # 固化存量 warning 豁免
kb index --check --repo docs                            # 索引是否漂移(CI 用, 漂移退 1)
```

`--baseline` 默认读 `<repo>/.kb-lint-baseline`。基线只豁免存量 warning; 新 warning 在
`--strict` 下即失败; 基线里已修复的条目会提示"过期"但不阻断。CI 见
`.github/workflows/kb-ci.yml`, push 门禁见 `scripts/install-gate.ps1`。

## 7. 接入新仓库

前提: 业务仓与 Agent-KB **同一父目录**(定位解释器靠此约定), 且 Agent-KB 已建 venv。

```powershell
# ① 生成去绝对路径的 .mcp.json(kb 目录不存在时自动建骨架; 未挂 submodule 自动降级单层)
<Agent-KB>\.venv\Scripts\python.exe -m kb.cli init --repo docs --kb-dir docs

# ② 自检(venv / 门禁依赖 / submodule / index 漂移 / lint / 钩子新鲜度 / .mcp.json)
<Agent-KB>\.venv\Scripts\python.exe -m kb.cli doctor --repo docs

# ③ 重载 Agent 的 MCP 配置(重启会话), 即得 kb_* 工具面
```

`init` 常用参数: `--kb-dir docs`、`--repo-name <小写名>`、`--mcp-name kb`、
`--force`(覆盖已有)、`--serve-url` + `--token`(团队态, 见 §8)。
生成的 `.mcp.json` 只写**相对**解释器路径与地址, 不含任何令牌, 可安全入库。

可选增强:

```powershell
git submodule add <Agent-KB-url> .agent-kb          # 双层检索
<Agent-KB>\.venv\Scripts\python.exe -m kb.cli init --repo docs --kb-dir docs --agent-kb .agent-kb --force
powershell -File <Agent-KB>\scripts\install-gate.ps1 -RepoRoot .   # 装 push 门禁
```

## 8. MCP 工具面(Agent 侧)

`kb init` 生成的配置对应 `python -m kb.mcp --repo <kb载体> [--agent-kb <层>] --repo-name <名>`。
暴露的工具与其 CLI 对应关系:

| MCP 工具 | 作用 | 约束 |
| --- | --- | --- |
| `kb_search` | 双层检索, 只回元数据+摘要 | draft 永不返回; 外接源 id 形如 `source://<源>/<id>` |
| `kb_get` | 按 id 读全文 | 命中 `kb_search` 后才调, 省 token |
| `kb_related` | 关联/被引用条目 | 只回元数据+摘要 |
| `kb_create` | 沉淀新条目 | 强制 draft/speculative/project; 查重命中即失败并返回候选 id |
| `kb_update` | 更新本项目 draft | accepted/proposed 一律拒绝(人工 CLI 专用) |
| `kb_review` | 自主终审本项目条目 | accepted 必须带 evidence + 提升 confidence |

## 9. 观测面板与检索埋点

```powershell
kb web                        # 打开面板(无 serve 时静默代拉起, 空闲自杀)
kb web --all                  # 直接进多项目联邦视图
kb web --no-browser           # 只打印 URL
kb serve --port 4320          # 观测服务端(只读 REST + SSE, 默认仅 127.0.0.1)
kb serve --install-autostart  # 团队常开: 注册登录自启(不落盘令牌)
kb serve --uninstall-autostart
kb spider-live                # 检索事件实时直播到 prompt-spider-ui(需 Node 20+)
kb trace list --zero-hit --repo docs      # 零命中记录
kb trace show <id> --repo docs
kb trace export --latest --format spider -o replay.json   # 导出蜘蛛回放数据包
kb trace report --format md               # 零命中周报(高频待消化词 + 消化率)
```

trace 落盘到本仓 `traces/YYYY-MM-DD.jsonl`(入 git, 只含元数据与摘要级信息, 永不写正文)。
优先级: 命令显式 `--trace/--no-trace` > 环境变量 `KB_TRACE` > 仓根 `.kb-trace` 标记 > 默认关闭。
`traces/` 由每日定时任务自动 commit(不 push), **不要**把它混进功能提交。

团队常开态(非本机 bind 必须带令牌, 否则 serve 拒绝启动):

```
① 常开主机: kb serve --bind 0.0.0.0 --port 4320 --token <随机32位> --install-autostart
② 成员机:   kb init --repo docs --serve-url http://kb.internal:4320 --token <令牌>
            → 凭据写用户级 ~/.kb/config.toml(不入库)
③ 业务仓 .mcp.json 只有地址(KB_INGEST_URL), 令牌永不进项目仓
④ 成员浏览器 kb web → 连团队实例, 不可达则降级本机并横幅明示
```

环境变量一览: `KB_TRACE`(埋点开关)、`KB_SERVE_URL` / `KB_SERVE_TOKEN`(读侧)、
`KB_INGEST_URL` / `KB_INGEST_TOKEN`(上报侧)、`KB_SOURCES`(外接知识源, 如 `tdbm`)、
`KB_SPIDER_HOME`(prompt-spider-ui 克隆根)。优先级均为**环境变量 > ~/.kb/config.toml**。

## 10. 常见问题

| 现象 | 原因与处置 |
| --- | --- |
| `kb: command not found` | 未 `pip install -e .` 或 venv 未激活; 改用 `.venv\Scripts\python.exe -m kb.cli` |
| `init` 报 "Agent-KB venv 未装配" | Agent-KB 主仓缺 `.venv`; 按 §1 建 venv, 或确认业务仓与 Agent-KB 是同级目录 |
| `doctor` 报 index stale | 生成物漂移: `kb index --repo <载体>` 后重跑 |
| `index --check` 恒 stale | `repo` 字段大小写漂移; 用 `--repo-name <小写名>` 重建后提交 |
| lint 存量 warning 刷屏 | 历史债: `kb lint --update-baseline` 固化, 之后 `--strict` 只挡增量 |
| `kb spider-live` 找不到克隆 | 加 `--spider-home <路径>` 或设 `KB_SPIDER_HOME`, 并在其 `mcp/` 内 `npm ci` |
| 面板提示 traces/ 不存在 | 观测未开: 业务仓 `.mcp.json` 的 env 加 `"KB_TRACE":"1"` 或重跑 `kb init` |
| MCP 工具面不出现 | Agent 未重载 MCP 配置; 重启会话后再看 |
