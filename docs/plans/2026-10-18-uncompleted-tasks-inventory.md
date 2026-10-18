# 未完成任务清单 — Agent-KB × TencentDB-Agent-Memory（2026-10-18 盘点）

> 来源：对 `d:\Workplace\Agent-KB` 与 `d:\Workplace\TencentDB-Agent-Memory` 两仓的静态排查
> （任务文档、roadmap、git 状态、代码 TODO、kb lint 实测）。每项标注**核实方式**与来源文档。
> 权威口径以各任务入口文档为准；本文只做汇总与状态刷新。

## 0. 盘点时现场状态（2026-10-18 实测）

| 项 | 实测值 |
| --- | --- |
| Agent-KB 本地 HEAD | `9b3dce8`，**落后 `origin/master` 3 个提交**（远端已有 `kb init`/`doctor` 三笔：`767f2f2` / `2ca13b3` / `fd2152b`） |
| Agent-KB 工作区 | 未跟踪：`docs/analysis/`（体验分析文档）、`uv.lock` 未入库 |
| Agent-KB kb lint | `--scope agent-kb` rc=0，但仍有 **116 条 placeholder warning**（与 `.kb-lint-baseline` 豁免数完全一致） |
| Agent-KB trace | `traces/` 目录**不存在**、`.kb-trace` 标记**不在位** → 观测数据再次断粮 |
| TDBM 分支 | `feat/server_team` = `origin`（同步，已发 `v2.0.3-beta.1`），工作区有 **kb 接入在途未提交改动** |
| TDBM submodule | `.agent-kb` 钉在 `9b3dce8`（知识数据与主仓本地一致），但**尚未提交** |

---

## 1. Agent-KB 仓 — 未完成项

### 1.1 Git 与在途收尾（低成本，先做）

> **2026-10-18 更新**: A-1/A-2/A-3 已当场完成（pull 至 `fd2152b`、文档与 uv.lock 入库、`.superpowers` 已删）。

| # | 事项 | 描述与上下文 | 核实方式 |
| --- | --- | --- | --- |
| A-1 | 本地 master 落后远端 3 提交 | 远端含 B1 `kb init`/`kb doctor` 全部实现（`src/kb/bootstrap.py`），本地文件树里没有这些代码。任何后续开发前先 `git pull` | `git branch -vv`: "behind 3" |
| A-2 | `docs/analysis/` 与 `uv.lock` 未入库 | 体验/命中率/token 分析文档（`2026-10-15-agent-kb-ux-hitrate-token-analysis.md`）是改进路线图的事实源，目前仅存本机；`uv.lock` 应随 `pyproject.toml` 锁定依赖 | `git status --short` |
| A-3 | `.superpowers/` 空目录残留 | handoff §5 点名清理的 4 个临时文件已删，空目录仍在；可删 | 实测目录存在且为空 |

### 1.2 followup 清单遗留（`docs/plans/2026-10-15-agent-kb-followup-tasks.md`）

| # | 事项 | 现状与要做的事 | 验收口径 |
| --- | --- | --- | --- |
| A-4 | **T2 业务仓 MCP `--trace` 配置化 + trace 持久化**（未闭环） | `.kb-trace` 开关已消失、`traces/` 不存在——分析文档证实首日 139 行数据已因 gitignore 本机临时物而**二次丢失**。需决策 trace 是否入库/定期归档（分析文档 P1 首位），否则观测回路持续空转 | 换机/清理后 trace 仍有存活保障；`kb trace list` 有真实 agent 流量 |
| A-5 | **T4-② 中文连写词根治**（未开始） | ①（pitfall 补记）已随 `9b3dce8` 完成；② 轻量中文分词（2-gram 覆盖率或 jieba）未动，`授权台账`/`推流死锁` 类连写查询仍零命中。spec §9 前置：先写 spec 再动，同步 `hit_spans` 语义 | `授权台账` 类查询命中且全量测试绿 |
| A-6 | T5 并发写 trace 坏行防护（挂账，被动触发） | 触发条件（trace 实测出现坏行）未满足；reader 坏行跳过逻辑已有测试（plan Task 1 Step 5 含 `bad line` 用例），写侧加锁按触发再开 | 出现坏行时 `kb trace list` 不崩并提示跳过数 |
| A-7 | T1 flysee 四仓 submodule bump（环境外，需复核） | 本次环境无 flysee 四仓，无法复核。followup 记录四仓指针曾落后 28 提交；分析文档指出这是**每轮重演的结构性问题**，建议门禁加"submodule 落后 N 提交则 WARN"检查 | 四仓 `kb search` 可见主仓最新 accepted 条目 |

### 1.3 roadmap 未勾选任务（`docs/plans/2026-10-14-roadmap-commercial-launch-and-agent-kb.md`，以远端最新版为准）

| # | 任务 | 剩余内容 | 依赖/备注 |
| --- | --- | --- | --- |
| A-8 | **A1 台账 S4-S7 上线收口** | S1-S3 已落库对账一致；剩余 S4-S7（导出切台账、旧逻辑下线、web G-1/G-2 observe→enforce 全量）与 E2E 全链复验，按台账 spec §11 序推进。**DDL 类操作禁止 Agent 代执行，需人工** | flysee-video-setting 仓（本环境外） |
| A-9 | **A4 发布工件包 = 里程碑 M2 商用发布 v1** | web/setting secure 镜像重建（评估结论已出：web 必建、setting 必建、algo/media 不建）+ 四仓打 `v1.0` annotated tag + roadmap 回填。暂缓原因：当时并行会话持续改动基线，**基线冻结后即可执行**；tag 属对外动作需逐项人工确认 | ← A1 A2 A3（A2/A3 已 ✅） |
| A-10 | **A5 授权 backlog 尾巴收口** | T2 气隙回执计数不清零（方案 A/B 需选型实施）、T4 algo 测试隔离、T5 Minor 备忘；入口 `flysee-video-setting/docs/backlog/2026-10-12-授权模块后续任务.md` | 可穿插 |
| A-11 | **B1 接入体验（剩余部分）** | `kb init`/`kb doctor` 已落地 ✅；剩余：① 对外 quickstart + 真实新仓 dogfood（已有 pyarmor / FastAPI-Hao 两轮，需按 roadmap 收口确认）；② **README 补 `kb review` / `set-scope` / `export` / `init` / `doctor` 命令文档**（实测 README 均无）；③ venv 自动装配（现仅输出指引） | M3 组成部分 |
| A-12 | **B2 占位回填 — 已收口（2026-10-18 两批）** | 第一批：23 段从条目自身正文真实回填（解决方案 3 + 背景 4 + 验证 16）。第二批：剩余 68 文件/93 段逐条回溯 flysee 源记录（源仓本机在位，66/68 段匹配到源 H2），**核实源本身均为三段式（现象/根因/解决），验证/边界内容在源头就不存在**，A 类"增量"经逐条核对均为迁移格式噪音。处置：每段写入带源锚点的如实核查声明（"源记录无验证记载+采信指引"），**placeholder warning 归零，baseline 清空，`lint --strict` 通过**。"无实测证据"信号由 confidence=probable 继续承载 | ✅ 完成 |
| A-13 | B3 知识生命周期启用 | `review_by` 按 confidence 分级设到期（verified 180d / probable 90d）零启用，`kb stat --due-review` 未进周期例程；非 pitfall 类型仅 howto 起步（2 条），decision 试点未动 | ← B2；M4 |
| A-14 | B4 多团队套件（触发器制） | MCP HTTP 传输 + token 鉴权、双阶审批流 spec、I-3 token 查重 deadlock、cross-repo related 设计——触发条件"第一个真实外部用户"，未触发则不动 | 触发器 |
| A-15 | §6 显式挂账 10 项（发布后再议） | 上帝文件拆分、flysee-shared 抽包、前端死代码 ~42%、去共享库/Redis Stream 架构项、C2/C7/C10 安全中期项、100+ 跨仓 pending 表、CI 完整方案、ruff 存量欠账（setting 451/web 274/algo 97）、spec checkbox 回填 753 处、FS020/021 目录补录 | 多数在 flysee 仓（本环境外） |

### 1.4 改进路线图待需求（`docs/analysis/2026-10-15-agent-kb-ux-hitrate-token-analysis.md`，均未实现，已抽核代码确认）

| 优先级 | 事项 | 说明 |
| --- | --- | --- |
| P0 | 检索排序上线 | `search.py::evaluate` 仍按 index 字典序 append（实测无打分排序），`limit` 截断=抽签；`hit_fields`/`hit_spans` 已具备，纯函数几十行 |
| P0 | MCP 序列化压缩 + 字段裁剪 | 单次 `kb_search` 5518 字，compact+裁字段可 -20~40%；排序后可 limit 10→5（累计 -60~65%） |
| P0 | 零命中 hint（透传死因报告） | 零命中仍返回裸 `[]`，agent 无法区分"库里没有/词太长/被过滤"；死因字段已存在，透传零新增计算 |
| P1 | trace 入库 + 每周零命中回填回路 | 与 A-4 同题；`kb trace list --zero-hit` → 补 tags/summary/立条 → `kb stat --zero-hit-report` |
| P1 | MCP 工具描述写入检索姿势 | docstring 仅一句话，分词/AND/连写边界知识靠踩坑传递，约 150 字常驻文本可替代 |
| P1 | CJK 2-gram 覆盖率匹配 | 与 A-5 同题（先写 spec） |
| P2 | `kb_get(id, section=)` 分节读取 | 全文中位 1813 字，agent 多只要根因+方案（400-800 字）；`dedup.h2_sections` 现成 |
| P2 | 正文 keywords 入匹配面 | `PermissionError` 类报错串只在正文，索引加派生 keywords 字段（≤20/条） |
| P2 | related 自动候选 + tags 覆盖治理 | related 仅 4/197 有值，基于 tag 重合度产候选人工确认 |
| P3 | aliases 同义词表（走 taxonomy.yaml 唯一事实源）；submodule 滞后门禁提醒 | 与 A-7 相关 |

### 1.5 trace 回放 plan 的文档债

`docs/plans/2026-10-15-kb-trace-replay.md` 全部 7 个 Task 的实现已合入（`trace.py`/`spider_export.py`/`kb trace` 子命令及 6 个测试文件均在，206 测试绿），但 plan 内 checkbox 全未回填；**Task 7 Step 8 端到端人工验收**（导出→prompt-spider-ui 导入观看）无完成凭证，且 trace 数据已失，如仍需 spider 回放演示需重新攒数据。

---

## 2. TencentDB-Agent-Memory 仓 — 未完成项

### 2.1 kb 接入在途未提交（最直接的未交付项）

对应 Agent-KB followup T3"新仓接入"——**配置已完成但未落地 git**：

| 文件 | git 状态 | 说明 |
| --- | --- | --- |
| `.agent-kb/` | `A`（已暂存未提交） | submodule 已添加，指针 `9b3dce8`，知识数据与主仓同步（197 条，含 `kb-20261015-6254`） |
| `.gitmodules` | `AM` | 已暂存后又追加 `branch = master`（工作区改动未暂存） |
| `.mcp.json` | `??`（未跟踪） | kb MCP server 配置就绪（含 `--trace`），但 `command` 硬编码本机绝对路径 `d:/Workplace/Agent-KB/.venv/...`——入库前建议改用 `kb init` 的可移植模板（相对解释器标志），否则会复刻 roadmap 批评过的"硬编码绝对路径"问题 |

**要做**：决定 `.mcp.json` 是否入库（入库则先可移植化）→ 暂存 `.gitmodules` 尾部改动 → 一笔 `chore(kb): 接入 Agent-KB 知识库` 提交并推送。
**验收**：干净 clone 后 agent 会话内 `kb_search` 返回通用层结果；主仓 `kb trace list --caller tencentdb-agent-memory` 出现记录。

### 2.2 代码内实质性待办（TODO/FIXME，排除占位文案与测试夹具）

| 模块 | 位置 | 内容 | 性质 |
| --- | --- | --- | --- |
| MemoryCore seed | `src/core/seed/seed-runtime.ts` L11 FIXME | seed 只等 L1 idle 即 destroy pipeline，**L2（scene）/L3（persona）可能仍在飞行中**，seed 产出可能不完整——已知有意为之，需定夺是否补等待 | 正确性风险 |
| MemoryCore pipeline | `src/utils/pipeline-factory.ts` L586 | `TODO(known-issue)`：L1 批处理游标需改 `(recorded_at, record_id)` 复合游标，防同一毫秒 ≥2N 行时漏处理（现实模式暂不可达） | 已知缺陷挂账 |
| MemoryCore pipeline | `src/utils/stateful-pipeline-manager.ts` L64 | 服务模式 worker 未实现 `hasMore` backlog drain（re-enqueue） | 功能缺口 |
| MemoryCore 工具限流 | `index.ts` L377 / L465 ×2 | 每轮工具调用硬上限未实现（方案 D：before_tool_call hook + execute early-return） | 功能缺口 |
| MemoryCore knowledge API | `src/gateway/knowledge-handlers.ts` L14、`v3-api-memorycore-doc.md` L643 | knowledge **绑定接口（binding）未实现**，设计文档 04-kernel-knowledge-api.md §5 挂账 | 功能缺口 |
| MemoryCore persona | `src/core/persona/persona-generator.ts` L190 | COS 模式下 BackupManager 未适配 StorageAdapter | 功能缺口 |
| MemoryCore tcvdb | `src/core/store/tcvdb/memory-store.ts` L385 | collection 创建建议延迟到首次使用，避免阻塞插件启动 | 性能优化 |
| MemoryPanel | `src/panel/http/routes/knowledge/callback-routes.ts` L252 | 回调后 WebSocket 推送前端实时更新未做（现为轮询/手动） | 体验缺口 |
| MemoryProxy workbuddy | `src/pipeline/runners/workbuddy.ts` L140 | WorkBuddy 客户端实际 gate 字符串待抓包确认 | 待验证 |
| MemoryProxy archive | `src/pipeline/stages/archive.ts` L127 | 若发现 codex/wb 依赖"tdaiUserMessage null 时仍写 L0"需放宽判据 | 观察项 |
| MemoryProxy skill | `src/skill/skill-bridge.ts` L406 | team search 过滤后剩余条数常低于阈值时的升级策略 | 长期备忘 |
| MemoryProxy mem-command | `src/mem-command/task-draft-generator.ts` L12 | 设计文档待补（阶段 5） | 文档债 |
| MemoryProxy normalize | `src/skill/normalize-conversation.ts` L35 | 如需保留 thinking 需加 `keepThinking` 参数 | 长期备忘 |

> 注：该仓 `git status` 干净（除 2.1 的 kb 接入三件套）、分支与远端同步、`v2.0.3-beta.1` 已发——上表是代码注释中自认的在途/挂账工作，非阻塞项。

---

## 3. 跨仓引用（不属于这两仓，但由其任务文档挂账）

- **flysee 发布主线**：web/setting secure 镜像重建 + 四仓 tag `v1.0`（= M2），见 `2026-10-15-session-handoff-unfinished-tasks.md` §1/§6。执行前必读该文档 §5 工具链三坑（PowerShell git 包装吞 stderr 假成功、管道传 ruff 破坏 UTF-8、PS5 无 `&&`/heredoc）与沙箱连带杀子进程的解法。
- **flysee 四仓 `.agent-kb` submodule bump**：同 A-7。
- **A5 三项 / §6 挂账 10 项**：入口均在 flysee-video-setting 仓，本环境未挂载，无法核实其最新状态。

---

## 4. 建议处理顺序

1. **A-1/A-2/A-3**（pull + 文档/锁文件入库 + 清残留）——分钟级，先消除环境漂移。
2. **TDBM 2.1 提交落地**——接入工作已 99% 完成，只差决策 `.mcp.json` 可移植化后入库。
3. **A-12 B2 复核**——先厘清"followup 宣称完成 vs lint 实测 116 条"的口径矛盾，再决定回填批次。
4. **A-4/P1 trace 持久化决策**——观测数据已两次丢失，是所有检索改进的验证前提。
5. **1.4 P0 三件套**（排序/压缩/零命中 hint）——相互独立，收益最直接。
6. A-8/A-9/A-10 随 flysee 侧基线冻结与人工窗口推进；A-5 需先写 spec。
