# AGENTS.md — Agent 入口

> 本文件是 AI Agent 的唯一常驻入口, 只回答三件事: **去哪找 / 怎么查 / 什么规则**。
> 不含知识正文; 细节按需下沉到 L2/L3(见下)。

## 这是什么

Agent-KB 是**跨项目研发知识库的事实源**, 配套 `kb` CLI(本仓 `src/kb/`, 入口命令 `kb`)。
知识分两处存放:

- **本项目知识**: 各项目仓内 `docs/kb/`(scope: project), 随代码版本化;
- **通用知识**: Agent-KB 仓 `kb/`(scope: stack/universal), 在各项目内以 submodule 挂载于 `.agent-kb/kb/`。

两处共用同一套 front-matter schema、模板、索引格式与 CLI。`kb/INDEX.md`、
`kb/index.jsonl` 与 `kb/index.draft.jsonl` 是 `kb index` 的**生成物**, 勿手改。

## 怎么查(三级披露)

| 层级 | 载体 | 内容 | 何时加载 |
| --- | --- | --- | --- |
| L1 | 本文件(AGENTS.md) | 位置、命令、规则 | 常驻(宿主装载, kb 不产生读取事件) |
| L2 | `kb/index.jsonl` 机器面(`kb/INDEX.md` 仅人读投影; 命令 `kb search`) | 标题 + 元数据 + 一句话摘要 | 判断相关性时 |
| L3 | `kb show <id>`(条目正文 markdown) | 单条全文 | 确认相关后 |

**标准路径**: 先 `kb search`(只回元数据+摘要+路径), 命中才 `kb show` 读全文。
禁止跳过 L2 直接批量读 L3, 浪费 token。`status: draft` 的条目不进检索索引。

**观测口径**: 每次 `kb search`/`kb_search` 落一条 L2 事件(`level=2`, `surface=index.jsonl`),
每次 `kb show`/`kb_get` 落一条 L3 事件(`level=3`, `surface=entry.md`); L1 由宿主装进
系统提示, kb 进程不参与, 因此**没有读取事件**——面板显示"不可观测"而不是 0。
"只看元数据"(有返回但同 trace 未读全文)由 `meta_only` 显式出数, 不再从字符数反推。

## 常用命令

所有子命令均支持 `--repo <路径>`(写在子命令之后, 默认为当前目录); 查通用知识用
`--repo .agent-kb`, 查本项目知识用 `--repo docs`。

```bash
kb new pitfall --domain frontend --scope project --title "示例标题" --generated --repo .
kb lint --scope project --repo .                # 校验; Agent-KB 仓用 --scope agent-kb
kb index --repo .                               # 重建 INDEX.md / index.jsonl
kb index --check --repo .                       # 检查索引是否漂移(CI 用)
kb search --query "vite hmr" --repo .           # 元数据+摘要检索, 默认 limit 20
kb search --type pitfall --domain frontend --confidence verified --repo .
kb show kb-20261012-7f3a --repo .               # 按 id 读全文
kb related kb-20261012-7f3a --repo .            # 反向链接
kb stat --repo .                                # 质量报告; --due-review 看待复核
kb promote kb-20261012-7f3a --to stack --repo . # 建议提升 scope(由人确认落地)
kb review kb-20261012-7f3a --to proposed --repo .   # 人工流转(draft→proposed→…)
kb review kb-20261012-7f3a --to accepted --as-agent --confidence verified --evidence "实测证据出处" --repo .  # agent 自审留痕(对齐 MCP)
kb set-scope kb-20261012-7f3a stack --repo .        # scope 终审落地(清 needs-scope-review)
kb export kb-20261012-7f3a --to-repo ../Agent-KB --to-scope stack --repo docs  # 跨仓上提(人工)
kb search --query "x" --repo docs --agent-kb .agent-kb   # 双层检索
kb init --repo docs --agent-kb .agent-kb        # 接入: 生成去绝对路径的 .mcp.json
kb doctor --repo docs --agent-kb .agent-kb      # 接入自检(FAIL 才退 1)
```

联邦 L2 记录契约(index.jsonl 行是外部异构源接入的唯一接口): `kb show kb-20261114-b226 --repo .`。

观测面命令(`kb web / serve / spider-live / trace`)与团队令牌配置见 README「观测面板」;
`traces/` 由每日定时任务自动提交, **不要**随手纳入功能提交。

`kb new` 的 `<type>` ∈ decision/spec/plan/pitfall/rca/howto/reference/retrospective;
`--domain` ∈ backend/frontend/database/devops/security/testing/build/algorithm/process/tooling。

## 沉淀门控红线(强制)

> 红线由工具面强制: `kb new --generated` 与 MCP `kb_create` 只可能产出
> draft/project/speculative; MCP `kb_review` 让 agent **自主终审本项目条目的状态**,
> 但 scope 上提仍人工。违规直接报错退出。

1. Agent 沉淀只产出 `draft`; **可自行终审状态**(`kb_review` 走
   draft→proposed→accepted), 无需等人工。但 accepted **必须**: (a) 已完成自行验证并附
   `evidence`, (b) 同时把 `confidence` 提升为 verified/probable——否则被拒
   (`speculative` 永不 accepted)。自审 accepted 自动打 `auto-reviewed` 标签 +
   `verified_by: agent` + `verification.evidence` 留痕, 供事后抽查回滚。
2. Agent **永远不能**改 `scope`(非 project); 认为值得上提 Agent-KB 时只做
   `kb promote <id> --to stack|universal` 式**建议**, 由人 `kb set-scope`/`kb export` 落地。
3. 沉淀前**必须**先 `kb search` 去重; 命中既有条目则更新(追加"新发现"), 不新建。
3b. 向既有条目**追加"新发现"时必须同步补 `tags`**: 检索面只有 title/tags/keywords/
    sections 四处, keywords 每段配额有限、sections 每段最多 20 个段落首句——只加正文
    不动 tags, 下一次 `kb search` 很可能搜不到这次追加的内容, 红线 #3 的去重随之
    失效(2026-10-29 线上实测: 追加约 1400 字后旧查询仍零命中, 补 tag 后立即命中)。
    **tag 语言须与查询习惯一致**: 补的 tag 若只有英文, 中文查询仍零命中(同日实测:
    `pre-push-gate`/`repo-name` 命中而 `pre-push 门禁 repo 名同源` 零命中, 补中文
    tag 后才命中)——中英各补一组, 别只补一边。
4. 无实测证据的结论**必须**标 `confidence: speculative`; 采信时默认只信 verified/probable,
   `speculative` 结论须自行验证后才可依据(检索本身不做 confidence 过滤)。
5. 单次任务最多沉淀 **3 条**(防刷噪音的节流点在新建); **自主终审 accepted 不限次**
   ——清理存量 backlog 不该被会话上限切成多轮, accepted 的硬约束只剩 evidence +
   confidence 提升 + `auto-reviewed` 留痕。
6. `kb_update` 可编辑本项目 draft/proposed; **编辑已 accepted 的条目会自动降级
   proposed**(结论被改动必须重审), 并清掉 `verified_by`/`verification`/`auto-reviewed`
   留痕、写 `revision` 审计字段。deprecated/superseded 终态不可编辑。

> **不要手改 front-matter**: confidence 提升不是"人工改文件", 而是一次
> `kb review <id> --to accepted --confidence verified --evidence "实测证据出处" --repo docs`
> (MCP 面同名为 `kb_review`)。手改 status/confidence 属绕过门控的违规操作。

## 收录标准

**值得进**: 有普适性(换一个项目/人还会再遇到) · 有根因(讲清机制, 不只表象) ·
可验证(有复现步骤、命令输出或数据)。

**不进**: 一次性环境配置(改天就失效) · 无根因的猜测与"试试就好" ·
任何密钥/凭证/内部敏感数据 · 已在代码注释/commit message 里自解释且无增量信息的内容。

## 格式契约

- **唯一事实源**: 枚举与正文骨架见仓根 `taxonomy.yaml`(新增 type/domain 只改这一处)。
- **元数据**: front-matter 校验依据 `schema/frontmatter.schema.json`(由 taxonomy 派生);
  必填 id/title/type/domain/scope/status/confidence/created/updated, pitfall/rca 加 severity。
- **正文**: 一条知识 = 一个文件 + 一个 H1; 六段式骨架按 type 裁剪, 模板在 `templates/`。
- **路径**: `kb/<type>/<domain>/<YYYY-MM-DD-slug>.md`; id 不可变, slug 可改不断链。
- 机器校验一律 `kb lint`, 不要人眼对字段。
