# 观测面板 B1–B4 交付后未完成任务清单（2026-10-20）

> 来源: PRD 制定 + B-1~B-4 开发会话。PRD 见 `docs/prd/2026-10-20-kb-observability-ui-hitrate-prd.html`。
> 里程碑 commit: `2c8c082`(PRD) / `64c0431`(B1+B3 检索) / `e64fbeb`(B2+B4 观测) /
> `1abff63`(B4 FR-6 联邦) / `b929175`(B4 spider-live)。255 测试全绿, 均已本地提交。

## A. 挂账开发项（代码已留接口, 需真实环境收口）

### A-1 TDBM 连接器真实实例联调 ✅（2026-10-20 完成）
- **描述**: `src/kb/sources.py::TdbmConnector` 按其仓内 `MemoryKnowledge/openapi.yaml`
  实现（`POST /wiki/search`、`x-tdai-service-id` 头、Envelope code=0）, 但**未经真实实例
  联调**, data 内页列表/字段名（path/title/snippet/score）是防御式宽容解析。
- **上下文**: PRD FR-6.3, TDBM 为默认外接源; 测试仅覆盖假响应解析与静默降级。
- **完成标准**: 起 TencentDB-Agent-Memory 实例（`d:\Workplace\TencentDB-Agent-Memory`）,
  配 `KB_SOURCES=tdbm` + `KB_TDBM_URL/SERVICE_ID/WIKI_ID`, 真检索+真读取通过;
  字段名若与假设不符只改 `_search/_get` 两处; 补一条真机 pitfall 到 kb。
- **收口记录**: 本机 npm+tsx 起实例（LLM_MODE=custom 指向 mock LLM）走完
  create→raw/write→ingest→ready（wiki-itvy6erg, 7 页）。真契约与假设差异三处:
  page/read 请求字段 `refs`（非 paths）、响应匹配字段 `ref`（非 path）、search 须显式
  取 `data.results`（links 也是 list）; Windows 服务端 path 混用 `\` 分隔符, 连接器两侧
  已归一化。`_search/_get` 已按真机修复, 单测按真 schema 重写, 256 测试全绿。
  真机 pitfall: `kb-20261020-67ae`（accepted/verified; 建议 scope→stack, 待人工
  `kb set-scope` 落地）。顺带发现并修复 TDBM 仓 Windows 可移植性缺陷
  （`wiki-service.ts` 硬编码 `/` 前缀比较致 raw/write 全线 400 traversal;
  `src/server.ts` 的 import.meta.url 自执行判断在 Windows 下不生效, 未改）,
  **改动在工作区未提交, 归属该仓维护方决策**。

### A-2 `--install-autostart` 系统服务注册未实现 ✅（2026-10-20 完成）
- **描述**: PRD FR-2.5 团队常开态要求 serve 崩溃后由系统管理器拉起
  （Windows 计划任务 / systemd）。当前团队态需管理员手工配置常驻。
- **上下文**: `kb serve --help` 无此参数; PRD 设计为"不自造守护, 交给系统服务管理器"。
- **完成标准**: `kb serve --install-autostart` 生成计划任务/systemd unit（幂等,
  含 `--token` 走环境变量不落盘的选项）, `--uninstall-autostart` 可撤销; 文档写清权限要求。
- **收口记录**: 新增 `src/kb/autostart.py` + `kb serve --install-autostart/
  --uninstall-autostart`（cli.py 与 serve.py 两处入口）。Windows 走 PowerShell
  cmdlet（schtasks.exe 在受管终端被策略整体拦截）, 关键坑是 `-AtLogOn` 必须
  `-User $env:USERNAME`（否则=任意用户登录语义需管理员）——已沉淀
  kb-20261020-9676（accepted/verified）; Linux/macOS 走 systemd 用户 unit
  （enable --now, 代码路径未实机验证, 本机无 systemd）。token 红线: 任务定义
  只含 serve 命令行, token 经 `setx KB_SERVE_TOKEN`/`systemctl set-environment`
  注入不落盘。真机验证: 注册成功 → 任务 Running → `/api/health` ok → 幂等重装
  通过。注意验证时先查 4320 端口占用（A-3 遗留 serve 进程曾致 health"假通过"）。

### A-3 MCP 真实链路端到端验证（spider-live + 面板直播） ✅（2026-10-20 完成）
- **描述**: spider-live 已用 CLI trace 真机验证; **MCP 进程内检索**（agent 经 kb_search）
  → trace → 面板 SSE/直播 的完整链路只过了内存单测, 未跑真实 MCP 客户端。
- **完成标准**: 在接入仓（含 `.agent-kb` submodule）用真实 Agent 会话检索一次,
  确认面板实时流出条目、spider-live 开会话、trace 落盘 schema=2 字段齐全。
- **收口记录**: 在 `TencentDB-Agent-Memory`（含 `.agent-kb` submodule）按业务仓
  `.mcp.json` 原样 spawn server 进程, 用官方 mcp Python SDK stdio 客户端（与 Agent
  侧启动方式等价）跑 `kb_search('uvicorn')`（6 命中）+ `kb_get`（3499 字符）：
  trace 落盘 search/get 成对、`trace_id` 关联、schema=2 全字段（含
  `returned_chars`/`layers`/`caller_repo=tencentdb-agent-memory`）断言通过;
  serve `/api/stream` SSE 实时收到同 trace_id 的 search+get 两条; spider-live 为
  每次检索开蜘蛛会话并输出回放 URL; `/api/callers`、`/api/feed` 可见新数据。
  验证脚本为临时件（Temp），未入库。零命中死因提示（FR-3.2）在同链路实测生效
  （`死于词匹配 197` + 改词建议）。

## B. 功能缺口（PRD 内已定义、本版未做或部分做）

### B-1 联邦视图"按源堆叠"列未实现 ✅（2026-10-20 完成）
- **描述**: PRD FR-5.2 项目矩阵应含 每项目按知识源（本地项目层/通用层/TDBM/Notion…）
  的命中占比堆叠 + 源健康列。现矩阵只有 caller×检索数/命中率/掉线; trace 已带
  `ext`（外接源命中与 health）与 `source://` 寻址, **数据面就绪, 聚合与前端未做**。
- **完成标准**: `stats.py` 增加按源聚合（source 取自 returned id 前缀 + layers/ext）,
  面板矩阵行加堆叠条; "外接·TDBM"用蜘蛛新增分支色（PRD 指定 #F34A87）。
- **收口记录**: `stats.by_source()`（project/stack/ext:<connector> 三分类, 计数口径
  与命中率同源: returned 条目归属; layers 明细缺失的老事件兜底记 stack 不虚增
  project）+ `_ext_health_latest()`（每源最近一次 ok/error）并入 `callers()` 行;
  面板矩阵加"按源堆叠"条（绿/橙/粉 flex 分宽, 悬浮显占比）与"外接源"健康列
  （●源名, 红=最近失败+悬浮 error）; 蜘蛛 live/export 两处 ROUTES 加 `ext` 第四
  分支 #F34A87（回放事件序 code→model→ext→you）。真机: 临时仓根 serve 注入带
  ext 的合成 trace, `/api/callers` 返回 `by_source={project:1, ext:tdbm:1}` +
  ext 健康, 单测 `test_stats_by_source.py` 4 例; 263 全绿。

### B-2 面板全屏蜘蛛回放（iframe 内嵌 prompt-spider-ui）未接 ✅（2026-10-20 完成）
- **描述**: PRD P1 表演层方案是 iframe 内嵌克隆仓回放（转换器 `spider_export.to_record`
  现成）; 本版交付了面板内原生 SVG 回放（点击条目弹窗）, iframe 全屏态未接。
- **上下文**: 用户已克隆 `e:\Workplace\prompt-spider-ui`, 并授权"后续功能修改可用该克隆"。
- **完成标准**: serve 增加 `/api/replay/<trace_id>` 输出 to_record JSON, 面板加
  "全屏蜘蛛"按钮 iframe 加载克隆仓回放页; 克隆仓零改动优先, 确需改则在其仓内单独 commit。
- **收口记录**: serve 新增 `/api/replay/<trace_id>`（to_record JSON, get 严格按
  trace_id 过滤）与 `/api/spider/<trace_id>`（懒启动 `SpiderBridge`: 首次请求才
  spawn 克隆 MCP → `spider_import_session` 返回 previewUrl; trace_id 缓存 ≤15 超限
  关最旧; 缺 Node/克隆依赖 → 503+指引且记住失败不重试）; 面板回放弹窗加"⤢ 全屏蜘蛛
  回放"按钮, 点击后 iframe 加载 previewUrl（token 走 #fragment, 由克隆页 sessionStorage
   自持）, 失败降级文案明确 SVG 回放不受影响。**克隆仓确需改动**（克隆仓 commit `fc25f75`
   单独提交, 已跑其全套测试 44+3 pass）: ① 第四分支 `ext` 落地（lib/config.js ROUTES +
  live-renderer/live.js/live-layout 布局 + mcp zod 枚举, PRD FR-5.2 指定 #F34A87——
  此前 B-1 加 ext 后回放/直播到克隆侧其实会被 validateEvent 拒绝, 本次真机暴露）;
  ② 转换器 `spider_id()` 归一原生 id（`source://…` 含 `/` 被对端 id 正则拒, search/
  get 两侧同函数保 you 匹配）。真机: 合成 ext trace → `/api/spider` 出 previewUrl →
  回放页 200 → 会话 counts ext=1/you=1; 缓存命中同 URL; 无 XFO/CSP 可 iframe。
  浏览器人工过一眼按钮交互留待下次开面板时顺带确认（逻辑路径均已 HTTP 级验证）。

### B-3 limit 10→5 与排序权重调参（等数据）
- **描述**: PRD 明确排序上线后 limit 收紧与字段裁剪以 trace 实测决策;
  面板 `cold_start` 口径也要求 ≥7 天连续数据才出命中率趋势。当前 trace 仅 1 天。
- **完成标准**: 积累 ≥7 天后跑 `kb trace report` + 面板 7d 窗, 数据支持则:
  MCP 默认 limit 10→5; 用回放集验证 `_FIELD_WEIGHT`/`_CJK_COVERAGE=0.6` 是否需调;
  结论回写 PRD §7 并把数值变更 commit（带回放对比证据）。
- **沙箱重放基建（2026-10-20 预置）**: `scripts/simulate-agent.py` 生成结构真实的
  多 caller 7 天数据集（仓外隔离目录, 红线: 永不写真实 traces/）。已用其验证:
  面板全链路(7d 窗/stats/callers 按源堆叠+外接健康/回放/全屏蜘蛛 counts ext=1 you=2)、
  `kb trace report` 消化率榜均可跑通。**初步方法学观察**（仿真数据, 仅验证分析流程,
  **不构成调参依据**）: 排名偏置点击下消费集中在 returned 前 3 位(34/44), 但 6-10 位
  仍有 ~9% 消费——limit 10→5 是否安全须看真实 get 的"搜索未返回后是否换词重查"信号,
  仿真无法回答该反事实。真实 7 天数据到位后按同流程重跑。

### B-4 零命中周报无人值守定时化 ✅（2026-10-20 完成）
- **描述**: `kb trace report` 命令已交付（FR-3.5）, PRD 的"周报"反馈回路还需**定时任务**
  自动产出并投递（仓内已有先例: due-review 每周一 09:00 cron, 见 commit `bcf1ce7`）。
- **完成标准**: 建每周一定时任务输出 `kb trace report --format md` 到约定位置;
  高频未消化词 ≥3 时提醒补 tags/立新条。
- **收口记录**: 建 schedule `b21cba28`（每周一 09:15, 错开 09:00 的 due-review）:
  跑 `kb trace report --format md` → 归档 `docs/reports/zero-hit-<周一日期>.md` →
  待消化词 count ≥3 时显式提醒消化动作 → 仅提交 `docs/reports`（不推送）。
  首跑 2026-10-26。当前窗口已有 1 个 ×3 词（`sse-e2e-验证`, 属联调噪音, 与本文档
  "测试遗留"备注一致——周报若长期被其霸榜, 再议 `--exclude`）。

## C. 待产品决策（PRD §7 开放问题, 需用户拍板）✅（2026-10-20 决策收口, 详见 PRD v1.4 §7.3）

> 用户拍板结果：C-1/C-5 延后并写明触发条件；C-2 维持现口径；C-3/C-4 预案文档化、
> 触发前不实现。原始问题记录保留如下备查。

1. **trace 入库体积容忍**: traces/ 已入库（B-2 决策）; 若年增长超预期, 备选: 月分卷 +
   `git gc` 约定, 或改为"仅 ingest 团队实例, git 存周报快照"。需 1–2 月后回看体积。
2. **"估算节省 token"展示措辞**: 现为 KPI 卡"估算节省 token ⓘ"+悬浮口径; 是否需要
   更保守（如只展示绝对字符数不折算 token）或提供对外更激进的口径开关。
3. **面板是否对外网/团队外可见**: 现仅 127.0.0.1 或内网 bind+token; 若要对外需前置反代+TLS,
   属于新 FR。
4. **令牌轮换与收权**: 现无轮换机制（离职收权=重发新 token 重启 serve）; 多团队场景前
   需定: 双令牌重叠期 or 每团队独立 serve。
5. **ingest/SSE 扇出容量**: PRD 承诺"spec 阶段压测定数"; 团队 >20 人或多个业务仓
   同连一把常开 serve 时需要小规模压测（ingest QPS、SSE 并发、watcher 轮询开销）。

## D. 运营/接入任务（非代码）

1. **业务仓批量接入**: 给 `TencentDB-Agent-Memory` 等业务仓配 `.mcp.json`
   `KB_TRACE=1`（重跑 `kb init` 即带）, 开始积累真实命中数据; 有 TDBM 的仓加
   `KB_SOURCES=tdbm`。这是 B-3 调参与对外展示"项目能力"数字的前提。
   **✅ 2026-10-20 该仓完成**: `kb init --kb-dir docs --force` 重生成 `.mcp.json`
   （相对解释器 `../Agent-KB/.venv/...` + `env.KB_TRACE=1` + 双层 `--repo docs
   --agent-kb .agent-kb`, 替换此前手配绝对路径版）; `docs/kb/` 骨架+索引已建;
   `kb doctor` 除 gate venv（业务仓自身缺 `.venv`, 属门禁安装范畴）外全绿。
   A-3 已用该配置跑通真链路并开始积累 trace。其余业务仓按同流程复制。
2. **README/AGENTS.md 增补观测面命令**: `kb serve / web / spider-live / trace report`、
   `KB_SOURCES`、`~/.kb/config.toml`、团队令牌分发流程（PRD FR-2.5 有四步示例可直接搬）。
   注意 AGENTS.md 定位是"唯一常驻入口, 只写去哪找/怎么查/什么规则", 详细放 README,
   AGENTS.md 至多加一行指针。
   **✅ 2026-10-20 完成**: README 新增「观测面板」章节（命令速查 + 环境变量开关 +
   FR-2.5 令牌分发四步 + 安全预案搬运: 反代+TLS / 双令牌轮换 / >50MB 月分卷 / >20人压测,
   口径与 PRD v1.4 §7.3 一致）; AGENTS.md 仅加两行指针（观测命令详见 README +
   traces/ 勿随手纳入功能提交）。
3. **trace 提交节奏约定**: traces/ 随检索不断变脏, 需要定: 随日常 commit 顺带提交 /
   pre-push 门自动带 / 每日定时任务提交。未定会让人频繁看到脏工作树。
   **✅ 2026-10-20 完成**: 用户拍板"每日定时任务提交"。Schedule `1114c13b`
   每天 18:30（与周一 09:00/09:15 两个周报任务错开, 且当天检索基本收尾）:
   仅 `git add traces/` + commit（无变更则空转）, 只 commit 不 push, 严禁越界 add;
   约定同步写入 README「trace 提交节奏」小节。首跑 2026-10-21。

## E. 仓库收尾杂项

1. **未提交改动（非本任务产生）**: `kb/pitfall/backend/2026-09-04-uvicorn-reload-sse-
   waiting-for-connections.md` 的 `review_by: 2027-04-11→2027-04-17`（生命周期任务滚动）,
   待确认后随下次提交入库。
2. **未推送远端**: ✅ 2026-10-20 已推送（`bcf1ce7..b929175` 5 个 commit →
   `origin/master`, 用户指示）。本会话 A-1/A-3/D-1 的改动仍在工作区未提交。
3. **克隆仓 `e:\Workplace\prompt-spider-ui`**: 本会话零改动（已装 `mcp/` 依赖）;
   后续若 B-2 需要改其前端, 在该仓独立 git 管理, 不与 Agent-KB 混提。
4. **测试遗留的零命中条目**: `traces/2026-10-20.jsonl` 含 `sse-e2e-验证` 等联调查询,
   会进零命中榜; 若显噪音可在周报口径里加 `--exclude` 或清理当日文件（trace_id 已入库,
   清理属改写历史, 建议保留并在榜单忽略即可）。

---
**优先级建议**: A-1（TDBM 联调）> A-3（MCP 真链路）> D-1（业务仓接入, 是 B-3 前提）>
A-2 / B-1 / B-4 > B-2 > C 类随批处理 > E 类收尾。
