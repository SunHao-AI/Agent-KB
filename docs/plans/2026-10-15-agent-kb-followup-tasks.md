# Agent-KB 后续任务清单（2026-10-15）

> 来源：2026-10-15 会话（kb trace 采集/回放落地 → 分词匹配修复 → MCP 自审终审放开）。
> 本文只管 **Agent-KB 仓自身**的后续任务；flysee 四仓发布主线（镜像重建、tag v1.0）见
> `2026-10-15-session-handoff-unfinished-tasks.md` §1，不在此重复。
> 每项含**实测现状**、要做的事、验收口径。P1 两项是"能力已合入 master 但真实使用场景失效"，
> 优先处理。

## 0. 现场速查（开工前重验，勿直接照抄）

| 项 | 值 |
| --- | --- |
| Agent-KB HEAD | `d820fd0`（已推 origin master，GitHub + Gitee 双远端） |
| 测试基线 | **194 passed**，`ruff check src tests scripts` 干净 |
| 知识条目 | 主仓 `kb/index.jsonl` **197** 条（+ draft 索引）；lint `--scope agent-kb` 零 error |
| trace 数据 | `traces/2026-10-15.jsonl` 139 行（当天积累）；`.kb-trace` 开关文件**在位**（已 gitignore） |
| 业务仓 submodule | 四仓（web / setting / algo / media）`.agent-kb` 全部钉在 **`b11c7f7`** |
| 业务仓 MCP | `command` 指向主仓 `.venv/Scripts/python.exe -m kb.mcp`（**editable 安装 → 代码是最新**） |

> **关键区分**：`.mcp.json` 的 `command` 走主仓 editable 安装，所以**代码修复**（分词 AND、
> UTF-8）对业务 agent 即时生效；而 `.agent-kb` submodule 只提供**知识数据**，落后即导致新条目
> 不可见。这两件事容易混淆，也是 P1-1 的根因。

---

## 1. P1 — 已合入但对真实场景失效

### T1 四仓 `.agent-kb` submodule 指针更新（知识断层）

- **实测现状**：四仓 submodule 全在 `b11c7f7`，落后主仓 HEAD **28 个提交**。业务侧检索
  `kb search --query "零命中" --repo docs --agent-kb .agent-kb` 返回 `[]`；主仓同查询命中
  `kb-20261015-6254`。submodule 索引 **195** 条 vs 主仓 **197** 条 —— 今天终审 accepted 并
  上提 `scope: stack` 的两条（多词零命中 pitfall `kb-20261015-6254`、kb trace 使用 howto
  `kb-20261015-9e2c`）业务 agent **完全看不到**。
- **要做**：逐仓 `git -C .agent-kb fetch origin master && git -C .agent-kb checkout d820fd0`
  （或 `git submodule update --remote .agent-kb`），回仓根 `git add .agent-kb` 提交
  `chore(kb): bump .agent-kb submodule → <sha>`，push。四仓注意各仓 pre-push（A6）会跑全量
  pytest，走 handoff §5 的 sh 链路 + 计划任务脱离会话，避免沙箱连带杀进程。
- **验收**：四仓 `kb search --query "零命中" --repo docs --agent-kb .agent-kb` 均命中
  `kb-20261015-6254`；`kb stat` 计数与主仓一致。
- **顺带**：submodule 更新会让各仓 `kb/` 下生成物（`INDEX.md` / `index.jsonl`）随指针变化，
  属预期 diff，勿手改。

### T2 业务仓 MCP 显式声明 `--trace`（可观测性从"依赖临时标记"转为配置化）

- **实测现状**（先纠正一个易误判）：Agent-KB 仓根的 `.kb-trace` 标记文件**已在位**，按开关优先级
  （CLI flag > 环境变量 > 标记文件 > 默认关），它对所有 kb 调用**全局生效**，业务仓 MCP 也不例外。
  所以"业务 agent 无 trace 记录"**不是配置缺失**，而是**这些会话尚未真正调用过 `kb_search`**。
  数据佐证：139 行里 `source=mcp` 且 `caller=flysee_*` 的 32 条**全部落在 17:01:38–17:02:19**
  （我当时的演示脚本打的，脚本已删）；`caller=docs/proj` 的 mcp 记录来自 pytest；17:42 之后
  除我手工 CLI 外无任何新记录。
- **仍要做的理由**：`.kb-trace` 是本机 gitignore 的临时开关，换机器 / 被清理即静默失去观测。
  把开关固化进配置才可移植。四仓 `.mcp.json` 的 args 追加 `"--trace"`，或改
  `env: {"KB_TRACE":"1"}`；长期是否常开由用户定（成本：每次检索多一次 append 写）。
- **验收**：改完重启业务仓 agent 会话，让 agent 跑一次 `kb_search`，回主仓
  `kb trace list --caller <仓名小写>` 能看到记录，且
  `kb trace export --latest --caller <仓名小写> -o replay.json` 直接出回放。
- **口径提醒**：`caller` 取发起检索的仓目录名小写（如 `flysee_video_web`），**不是**
  `--repo-name` 的值；筛错会误判"没采集"。

---

## 2. P2 — 接入与健壮性

### T3 TencentDB-Agent-Memory 接入 kb

- **实测现状**：该仓全仓 grep `agent-kb|kb_search|kb.mcp` **零匹配**，无 `.agent-kb`、无
  `docs/kb/`、无 kb 相关 MCP 配置 —— 它从未调用过 kb，trace 空白属正常而非故障。
- **要做**（用户当前正在该仓开发，接入后即刻可观测）：
  ```powershell
  cd d:\WorkPlace\Pycharm\TencentDB-Agent-Memory
  git submodule add d:/WorkPlace/Pycharm/Agent-KB .agent-kb   ; # 建议先 fetch 到最新再提交指针
  mkdir docs\kb                                                ; # 可选：本项目知识层
  # .mcp.json 加 server: command = 主仓 .venv/Scripts/python.exe,
  # args = ["-m","kb.mcp","--repo","docs","--agent-kb",".agent-kb","--repo-name",
  #         "TencentDB-Agent-Memory","--trace"]
  ```
  若该仓不建 `docs/kb`，`--repo` 直接指 `.agent-kb`。
- **验收**：该仓 agent 会话内 `kb_search` 返回通用层结果；主仓 `kb trace list` 出现
  `tencentdb-agent-memory` 的 caller。

### T4 中文连写词仍需字面完整命中（分词修复的残留边界）

- **实测现状**：`0b4a30e` 解决的是**空格分隔多词**（`license 授权` 0 → 命中）。但中文习惯连写、
  不打空格，`kb search --query "授权台账"` 仍返回 `[]` —— 它作为单 token 做整串 `find`，
  要求 title/tags/summary 拼接文本里存在**完全相同的连写串**。现有 pitfall 只写了多词场景，
  未覆盖这一半，agent 很可能再次困惑。
- **要做**：二选一，建议先做 ①。
  ① 给 `kb-20261015-6254` 追加"新发现"：中文连写仍需字面完整，检索习惯应为"挑一个最可能被
  原样写出的短词"（2–4 字）而非长串；并复核该条标题是否需要泛化。
  ② 若要根治：引入轻量中文分词（如按 2-gram 切分或接 jieba，注意依赖与索引体积代价），
  属检索语义变更，须先写 spec 再动，并同步 trace 的 `hit_spans` 语义。
- **验收**：①后 agent 侧通过 `kb_search` 能自查到该边界；②后 `授权台账` 类查询命中且全量测试绿。

### T5 并发写 trace 坏行防护（spec §9 挂账）

- **现状**：`trace.py` 用 `open(..., "a")` 单行 append；多 agent 会话并发检索时理论上可能交错
  出坏行，reader 目前对坏行的处理需复核（是否静默跳过而不整读失败）。
- **触发条件**：`traces/*.jsonl` 实测出现坏行即开工（现在 139 行全部完好）。
- **要做**：先给 reader 补"坏行跳过 + 计数上报"的测试，再决定是否在写侧加锁
  （可参考 `d026880` pre-push 单实例锁的 mkdir 原子模式）。
- **验收**：人为注入坏行的 fixture 下 `kb trace list` 不崩且明确提示跳过数。

---

## 3. P3 — 数据积累后与增强（勿提前做）

| 项 | 现状 / 触发条件 |
| --- | --- |
| 统计报表（命中率、热门条目、零命中 query 榜） | trace 仅 1 天 139 行，且真实 agent 流量尚未产生（见 T2）；spec §9 定的是**积累 ≥2 周真实 trace** 后做，倒计时应从业务 agent 真正开始调用起算 |
| `kb trace export` 支持 `unit:"word"` 逐词模式（蜘蛛逐词抓取动画） | 需要该演示效果时（spec §9） |
| 自建 `kb web` SVG 电影级回放页 | 转换器"导出→导入"仪式感不够用、或有损表达挡住深读时；线框与分镜 P0–P4 已评审存档于 spec §9 附注 |
| 实时直播（轮询 trace 自动跟进最新检索） | 自建 web 落地后二期评估 |
| 自建 `kb trace export --format html`（免起播放器，产物可分享） | 有对外分享需求时；注意"trace 不含正文"红线同样适用 |
| B2 占位回填（handoff §3 记"116 条未做"） | **2026-10-15"已关闭"系口径错误，已撤销**：当时只 grep `index.jsonl`/`index.draft.jsonl` 的 `待回填\|占位` 字样（0 命中），但 lint 检测的是**段内容剥离 HTML 注释后为空**，占位注释变体（`待补: …`）不被该 grep 覆盖。2026-10-18 复核实测 `kb lint` 仍报 116 条 placeholder warning。当日已完成**真实回填 23 条**（解决方案 3 + 背景 4 + 验证 16，均从条目自身正文提取并标注来源，不臆造），占位降至 **93 条**（验证 53 / 边界 40 / 其余少量），baseline 已同步收缩。剩余 93 条无源可提取，需逐条回溯 flysee 源记录或按 roadmap 口径如实降级处理 |

## 4. 交叉引用（不属本仓，仅提示依赖）

- flysee 发布主线 T4（web/setting secure 镜像重建）、T5（tag `v1.0` = M2）：见
  `2026-10-15-session-handoff-unfinished-tasks.md` §1、§6。其"T4/T5 暂缓"的原因是并行会话
  持续改动基线，与本文任务无阻塞关系，可独立推进。
- 工具链三坑（PowerShell git 包装函数吞 stderr 致门禁假成功、管道传 ruff 破坏 UTF-8 中文、
  PS5 无 `&&`/heredoc）与沙箱连带杀子进程的解法：同一份 handoff §5 及 §6 末段，**执行任何
  push 前必读**。

## 建议处理顺序

T1 → T2（两者合起来才让今天的投入在真实 agent 上生效；T1 是知识可见性，T2 是可观测性）
→ T3（新仓接入）→ T4-①（低成本消歧）→ 攒够 trace 后做报表。T5 与 P3 各项按触发条件被动启动。
