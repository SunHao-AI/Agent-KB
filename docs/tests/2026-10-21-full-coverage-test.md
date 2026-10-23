# Agent-KB 功能全覆盖测试设定（可复用）

> 首次执行: 2026-10-21 · 适用版本: 主仓 `main`(9efabe5 起)
> 目标: 验证 `kb` CLI 全命令与观测 Web 界面全功能是否正常; 本文档同时是后续
> 回归复用的**测试设定**(环境准备 → 用例 → 预期), 执行结果回填在末尾"执行记录"。
> 方法论: 缺陷处置遵循 systematic-debugging(复现→根因→最小修复→回归), 禁止症状级修补。

## 0. 红线约束

- 测试**不得污染**权威账本 `traces/`(git 管理): 数据驱动一律用沙箱目录
  (`scripts/simulate-agent.py --out <仓外目录>`), 该脚本自带拒写仓根的红线。
- 走查期间本机 CLI 检索一律 `--no-trace`(或 `$env:KB_TRACE="0"`), 避免把测试查询
  混进真实命中率统计。
- 测试产生的临时仓/临时条目放在 `$env:TEMP\kb-test-*`, 结束后删除。

## 1. 环境准备

> **前置红线(强制, 每次测试起手第一步): 先杀干净上一轮残留的 serve, 再启动新代码。**
> 教训来源: 本仓多次踩坑——serve **启动时一次性读入 index.html**, 残留旧进程会一直"服务旧
> HTML"; 且同一端口可能叠**双进程**(同秒两份), 改前端后测不到新代码、SSE 不广播。
> 因此测前必须: ① 全量枚举并杀掉旧 serve → ② 确认目标端口 0 监听 → ③ 再全新启动。

```powershell
cd d:\Workplace\Agent-KB
# ① 杀干净旧 serve(两种 CommandLine 形态都要覆盖: exe 带引号 与 python -m 模块形态)。
#    正则必须是 kb(\.exe"?)?\s+serve|kb\.cli\s+serve, 否则漏杀模块形态。
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'kb(\.exe"?)?\s+serve|kb\.cli\s+serve' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
# ② 确认目标端口已无监听(以 4321 为例), 有输出说明还有残留, 回到 ①
Get-NetTCPConnection -LocalPort 4321 -State Listen -ErrorAction SilentlyContinue
# 依赖: Python 3.10+(实测 3.12)、Node 20+(仅全屏蜘蛛回放桥需要)
.\.venv\Scripts\pip install -e ".[dev]"     # 已 editable 安装可跳过
.\.venv\Scripts\python.exe -m pytest -q      # 全量单测基线
# 沙箱数据(多 caller/外接源/零命中/已读 全形态, 幂等可重生成):
.\.venv\Scripts\python.exe scripts\simulate-agent.py --out $env:TEMP\kb-sim --days 7 --seed 42
# 用沙箱起观测服务端(独立端口, 避开 4320 上可能常驻的实例):
.\.venv\Scripts\kb.exe serve --repo $env:TEMP\kb-sim --port 4321
# 浏览器打开 http://127.0.0.1:4321/ ; 真实数据对照则:
.\.venv\Scripts\kb.exe serve            # 默认 4320, root=本仓 traces/
```

## 2. CLI 冒烟矩阵

约定: `KB` = `.\.venv\Scripts\kb.exe`; `TMP` = 临时测试目录。
退出码是断言主体, stderr 文案次之。

### 2.1 常规路径

| # | 命令 | 预期 |
|---|------|------|
| C1 | `kb --help` / 各子命令 `--help` | exit 0, 列出全部子命令 |
| C2 | `kb new howto --domain tooling --scope project --title <t> --repo TMP`(先 `kb init --repo TMP --kb-dir docs`) | exit 0, 打印文件路径, status=proposed, 套用模板 |
| C3 | `kb new pitfall --domain backend --scope project --title <t> --generated --repo TMP` | exit 0, status=draft + confidence=speculative(门控) |
| C4 | `kb lint --scope project --repo TMP` | exit 0, 无硬错误 |
| C5 | `kb index --repo TMP` → `kb index --check --repo TMP` | 先打印 3 个 wrote 路径, check 输出 `index up to date` exit 0 |
| C6 | 手改条目正文后直接 `kb index --check` | `index stale` exit 1(漂移可检出) |
| C7 | `kb search --query "<已有词>" --repo TMP --no-trace` | exit 0, JSON 数组, 只含元数据+摘要(无正文) |
| C8 | `kb show <id> --repo TMP` | 全文; 未知 id → `not found` exit 1 |
| C9 | `kb related <id> --repo TMP` | JSON(有 related 则含之) |
| C10 | `kb stat --repo TMP` / `--due-review` / `--needs-scope --format md` | JSON / JSON / Markdown 表格 |
| C11 | `kb review <id> --to proposed --repo TMP` → `--to accepted --evidence "..." --confidence verified` | status 流转成功并打印 front-matter |
| C12 | `kb promote <id> --to stack --repo TMP` | front-matter 加 needs-scope-review 建议, 不改 scope |
| C13 | `kb set-scope <id> stack --repo TMP` | scope 落 stack, 清 needs-scope-review |
| C14 | `kb export <id> --to-repo <另一临时仓> --to-scope stack --repo TMP` | 目标仓出现条目, `source.project` = 源仓名(非 kb-dir 尾名) |
| C15 | `kb init --repo TMP2 --kb-dir docs`(未挂 submodule) | 单层 .mcp.json, 无绝对路径泄漏 |
| C16 | `kb doctor --repo TMP2` | 全 PASS/WARN, exit 0; FAIL 才 exit 1 |
| C17 | `kb trace list --repo $env:TEMP\kb-sim` / `--zero-hit` / `--caller agent-kb` | 表格含时间/caller/命中/query+trace_id |
| C18 | `kb trace show <tid>`(取自 C17) | 单事件 JSON |
| C19 | `kb trace export --latest --repo $env:TEMP\kb-sim -o $env:TEMP\t.json` | 生成 spider 格式 record, 含 steps |
| C20 | `kb trace report --repo $env:TEMP\kb-sim` / `--format json` | 零命中榜+消化率; json 结构含 digest_rate |
| C21 | `kb web --no-browser --port <空闲口>` | 打印 URL, 后台代拉起 serve 成功 |

### 2.2 负例与红线

| # | 命令 | 预期 |
|---|------|------|
| N1 | `kb serve --bind 0.0.0.0 --port <口>`(无 token) | **拒绝启动** exit 2, 提示必须 token(红线) |
| N2 | `kb review <draft条> --to accepted --as-agent --repo TMP`(无 evidence) | exit 1 拒绝(agent 自审必须留证据) |
| N3 | `kb review <id> --to accepted --confidence speculative --evidence x --repo TMP` | 拒绝(speculative 永不 accepted) |
| N4 | `kb lint --scope wrong --repo TMP` | argparse exit 2(拼错即拒, 不静默) |
| N5 | `kb new` 重复标题(高相似) | `duplicate` candidates JSON exit 1(查重门控) |
| N6 | `kb trace export`(id 与 --latest 同给/同不给) | exit 2 二选一 |
| N7 | `kb search --query "绝对零命中词xyz" --no-trace` | exit 0 空数组(不报错) |
| N8 | `kb spider-live`(无 Node/未装克隆依赖时) | 友好报错 exit 2, 不裸 traceback |

## 3. Web 界面全功能走查(浏览器)

数据源: 沙箱 `$env:TEMP\kb-sim`(serve --port 4321)。每用例记录"实际=预期?"。
浏览器须开 DevTools Console, **任何未捕获 JS 异常都算 FAIL**。

| # | 区块 | 步骤 | 预期 |
|---|------|------|------|
| W1 | 加载 | 打开 `http://127.0.0.1:4321/` | 无 console 错误; 右上 `● 已连接`; KPI 4 卡有数 |
| W2 | 时间窗口 | 点 7天/30天/全部 | KPI/双榜随窗口变化; 按钮高亮切换; "全部"时无 since 参数 |
| W3 | 单项目视图 | 打开 `?caller=agent-kb` | KPI 只含该项目; 矩阵卡隐藏 |
| W4 | 联邦视图 | 点"多项目联邦" | 矩阵卡显示 3 caller; 列: 检索数/命中率/按源堆叠/外接源/最近活跃/状态 |
| W5 | 外接源健康 | 看 tencentdb-agent-memory 行"外接源"列 | ●tdbm 绿/红点(8% 注入错误), title 显示 ok/error |
| W6 | stale 标记 | 看矩阵 stale 列 | 有 >14d 未活跃行则红字"⚠ trace 掉线"(数据相关) |
| W7 | 矩阵下钻 | 点某项目行 | 切回单项目视图+绿色横幅"已下钻到项目 x" |
| W8 | 双榜 | 看热门被消费/零命中两列 | 条形宽度比例正确; 标题悬停显 id; 空态有引导文案 |
| W9 | 零命中追因 | 点某零命中行"追因→" | 检索流过滤到该 query 且滚动到位, 状态段=零命中 |
| W10 | 检索流快照 | 打开即见历史条目 | 圆点色: 绿=命中/红=零命中/黄=已读; 右侧 mono 显示 query·ms·时间 |
| W11 | 实时 SSE | 沙箱目录追加一行 search 事件(`Get-Content x | Add-Content ...`或重跑 simulate 尾部) | ≤2s 新条目出现在流首, 动画淡入 |
| W12 | 过滤 | 搜索框输入词; 分段切 全部/命中/零命中/已读 | 计数 `n/total` 正确; 无匹配显示空态文案 |
| W13 | 蜘蛛回放 | 点击命中条目 | **就绪态**: main 内播放坞展开(iframe, 不遮罩页面); **不就绪态**: 弹层 SVG 动画(蜘蛛巡游+触须+彩点飞入分箱); 头部含 query/caller/ms/trace |
| W14 | 键盘可达 | Tab 到条目按 Enter/空格 | 同 W13; Escape 先关 SVG 弹层, 再按则收起播放坞 |
| W15 | 零命中回放 | 点零命中条目 | 舞台显示"零命中 — 死因见左侧各层淘汰计数", 左侧列各层扫描/淘汰 |
| W16 | 播放坞换 trace | 坞已展开时再点另一条目 | iframe 就地换新 trace(dock 数量恒为 1, 不叠加); src 带 `chrome=none` |
| W17 | 回放缓存 | 收起坞→点细栏重展开 / 连续切多个 trace | 重展开秒开(serve 端会话缓存, ≤15 逐旧腾新); 无报错 |
| W18 | 断连恢复 | 杀掉 serve 再重启 | 右上变"● 断连(重试中)"红色脉冲; 重启后恢复"已连接" |
| W19 | traces 缺失 | 空目录起 serve → 打开 | 横幅提示"traces/ 目录不存在"而非白屏/报错 |
| W20 | token 鉴权 | `kb serve --port 4322 --token t123`; 直接开 `:4322/`; 再开 `:4322/?token=t123` | **页面 `/` 本身也受鉴权**(红线: 不泄露面板)→ 无 token 得 401 JSON; 带 `?token=t123` 页面+全部数据正常; 无 token 的 `/api/stats` 返回 401, 错 token 401 |
| W21 | API 面 | curl `/healthz` `/api/health` `/api/stats` `/api/feed` `/api/callers` `/api/replay/<tid>` `/api/replay/bad` | 200+合法 JSON; 未知 replay id → 404 JSON |
| W22 | ingest 口 | POST `/api/ingest` 合法/带 content 键/重发同 trace | ok / 400 / deduped:true(幂等) |
| W23 | 稀疏 trace 形态 | 手工 append 最小 trace(无 matched.title、rejected 无 filter 子键, 记得带 meta 首行) → 点其条目开播放坞 + curl `/api/replay/<tid>` | 桥正常出 iframe; replay 200 且 label 回退 id(禁止断连/Failed to fetch) |
| W24 | 竞态压力 | 快速连切 窗口×视图×单项目 ≥8 次, 再查 console | 0 未捕获 JS 错误; 最终态与最后一次点击一致(矩阵显隐/feed 数/连接态) |
| W25 | 追因兑现 | 零命中榜点一个**不在最近 30 条 feed** 的旧 query"追因→" | 自动扩大快照后命中并滚动定位(非"没有匹配"误导文案) |

## 4. 缺陷处置流程(每个 FAIL 走一遍)

1. 取证: console 报错原文 / 网络面板响应体 / 最小复现步骤, 稳定复现 ≥1 次;
2. 查变更: `git log -p -- <涉事文件>` 找引入点;
3. 追数据流: 从 UI 事件倒推到 serve 路由 → stats 口径 → trace 解析, 定位根因层;
4. 单一最小修复 + 必要时加回归测试(pytest 或走查用例);
5. 回归: `pytest -q` 全绿 + 该走查用例复测通过, 记入执行记录。

## 5. W11/W6 数据注入片段(走查复用)

```powershell
# W11 SSE 实时推送: 向沙箱当日文件追加一条最小 search 事件(目录已有带 meta 首行的文件时)
# 注意: 新建分片文件必须先写 {"kind":"meta","schema":2,...} 首行, 否则整文件被 _parse_file 跳过
# W6 stale 标记: 向 today-21d 日期分片写 meta+一条 search(caller 用独立名), 联邦视图"全部"窗口应显"⚠ trace 掉线(>14d)"
```

## 6. 执行记录(2026-10-21 首跑)

- 环境: Python 3.12.13(venv) / Node v22.23.2 / Windows / 基线 commit `9efabe5`
- **pytest**: 274 passed(修复后 275, 新增 1 条守护测试), 无失败
- **CLI 冒烟**: C1–C21 + N1–N8 全部 PASS(36 断言 0 失败)。要点: 门控红线(N1–N4/N6)、查重(N5)、
  漂移检出(C6)、export 的 source.project 取 git 仓名(C14)、doctor 裸仓 FAIL 明示(C16b) 均符合预期。
  `spider-live` 本机依赖就绪, 实测 3s 内对沙箱 7 条 search 建会话出 previewUrl(正向通过)。
- **Web 走查**: W1–W22 全部 PASS(其中 W6/W8–W17/W19–W22 在修复 D-1 后于 token 实例
  4332 与无 token 实例 4321 双态复测)。
- **缺陷清单与修复**(systematic-debugging 闭环, 均已回归):
  | # | 症状 | 根因 | 修复 | 验证 |
  |---|------|------|------|------|
  | D-1 | token 态(`serve --token` 或 `kb web` 开团队 URL)下页面可加载但 KPI/双榜/检索流全空, 误报"需要访问令牌" | 面板 `loadStats`/`loadFeed`/`/api/health` 三处 fetch 漏拼 token(同页 callers/spider/SSE 均带, 携带不一致) | index.html 三处 fetch 统一 `&token=` ; 新增静态守护测试 `test_panel_api_fetches_carry_token` | 浏览器复测 token 态全量渲染 OK; pytest 275 全绿 |
  | D-2 | serve 重启后连接指示永久停留"● 断连(重试中)", 即使 SSE 已重连成功 | EventSource 只挂了 `onerror`, 无 `onopen` 恢复路径 | 加 `es.onopen=()=>conn(true)` | 杀 serve→断连红色→重启→≤10s 自动恢复"● 已连接"(浏览器实测) |
- **环境观察项(非代码缺陷)**:
  1. 走查中发现 4321 端口 SSE 不广播 — 根因是前次会话残留的多个 serve
     进程父子链占住端口(Windows 下新起同端口实例行为异常)。清理残留进程后消失。
     复用本设定测试前**先杀干净旧 serve**(`Get-NetTCPConnection -LocalPort <port>`)。
- **知识沉淀**(落 `docs/kb/` scope=project, agent 自审 accepted, 带证据, 先 search 去重无命中):
  - `kb-20261021-0570` 前端多处手拼鉴权 token 参数漂移导致部分 API 静默 401
  - `kb-20261021-d3d2` traces 分片缺 meta 首行导致整文件事件被静默跳过
  - 观察项 1(残留进程)判定为一次性环境态, 按收录标准不进库。
- **遗留建议**: W16 全屏桥的 iframe 内容浏览器工具不可穿透, 其内部交互(导入导出/
  换肤)未覆盖, 属克隆仓职责范围。

## 7. 二轮整改记录(同日, 处理首跑遗留项)

| 项 | 处置 | 验证 |
|---|---|---|
| `kb new` 缺 `--severity` | 已加参数(choices 同 taxonomy 枚举): generated 路径透传 `create_draft(severity=)`, 人工路径覆盖模板默认 medium(与 MCP `kb_create` 对齐) | 实测 generated=high / human=critical / 缺省=medium 三路径 + lint exit 0 |
| 堆叠条 title 窄列截断 | 每段 title 改为**整条汇总**("project: N 次(x%) / ext:tdbm: N 次(y%)"), 段加 `min-width:3px` 保证小占比可悬停 | 浏览器实测矩阵堆叠段 title 为完整汇总串 |
| 面板 fetch 手拼 token | 新增 `apiUrl(path)` 统一注入器, **全部** 6 处 fetch + SSE EventSource 收口; 守护测试升级为"fetch/EventSource 的 /api/* 字面量禁止手拼, 必须走 apiUrl" | 网络面板实测所有请求带 token; 守护测试通过 |
| D-1 次生症状: 401 JSON 被当数组(`rows.slice is not a function`) | `loadFeed`/`loadMatrix` 补 401 短路(交 loadStats 统一出横幅), 消除 token 中途失效时的裸 TypeError | node --check 0 + pytest 275 全绿 |
| 控制台"24 条日志"逐条分析 | 除上述 TypeError 为真实(次生)缺陷已修外, 其余均为: 测试驱动 SSE 的正常断流(ERR_ABORTED/REFUSED/RESET, W18 场景), 测试脚本自身的探测语法错误(已改为合法脚本), 全屏桥 serve 停止时的 live.js 断流 | 详见对话记录; 无需改代码 |

## 8. 二轮回归走查(同日, apiUrl 重构后)

**回归项全部通过**: 无 token 态基础/KPI/双榜/feed 全量、窗口×视图 9 连切竞态压力(0 JS 错误)、
零命中追因、token 态 SSE 实时推送、token 态全屏桥(修复 D-4 后)。

**新发现并修复 2 个缺陷**:

| # | 症状 | 根因 | 修复 | 验证 |
|---|------|------|------|------|
| D-3 | 零命中榜对窗口内旧事件"追因→"→ 0 匹配 + 误导文案"试试更短的关键词" | 零命中榜聚合**整个窗口**, 追因实为前端过滤 feed 快照(仅最近 30 条)——承诺与实现对不上, 命中与否取决于事件是否碰巧在 30 条内 | 新增 `drillTo(q)`: 快照内 0 匹配自动扩 limit=500 重查再过滤(`loadFeed(limit)` 参数化) | 浏览器实测"postgres vacuum"(快照外)追因 → 自动扩快照命中 2 条, 计数 2/95 |
| D-4 | 全屏蜘蛛桥/`/api/replay` 对某些 trace 直接掐连接(浏览器只见 Failed to fetch) | `spider_export.to_record` 裸取 `m["title"]`/`rejected["filter"]`, 手工/早期 schema trace 缺键 → HTTP 线程 KeyError 未捕获 → 连接裸掐 | 读侧 `.get` + 语义回退(title→id, rejected→0); 新增 `test_sparse_legacy_trace_no_crash`(先失败后通过) | API 层 replay 由断连变 200(label 回退 id); 浏览器 token 态全屏桥 iframe 正常加载 |

**走查方法教训(写入设定)**:
1. **数据形态要多样**: 首轮全部用仿真脚本数据(字段齐全), 掩盖了 D-4 这类"读侧对稀疏
   trace 不防御"的缺陷; 二轮手工最小 trace 一次触发。后续走查必须同时喂仿真数据与
   手工最小/稀疏 trace。
2. **token 态须覆盖全部端点**: 首轮 W16 在全本机无 token 实例验的桥, token 态从未验过;
   后续 API 面用例(W21)应在带 token 实例上复跑一遍。
3. 竞态压力(快速连切按钮)可作为常设用例: 本次 9 连切 0 错误, 值得保留。

**本轮知识沉淀**: `kb-20261021-1b60` append-only trace 账本读侧裸取字段致 API 线程
KeyError 掐连接(accepted/verified/agent 留痕)。最终回归: pytest **276 passed**、
index/lint 全绿。

## 9. 三轮改造: 回放默认 iframe 化 + 命中行可读性(同日)

**交互模型变更**(用户拍板的折中方案):
- serve `SpiderBridge.ready()` 轻量探测(node + 克隆仓 + mcp 依赖, 不启动子进程, 结果缓存),
  经 `/api/health.spider_ready` 暴露。
- 面板 boot 读取该标志: **就绪 → 点条目直开全屏 iframe**(SVG 隐藏、动画停止, 点"收起"
  恢复 SVG 重播, 关弹层一并释放); **不就绪/桥意外失败 → SVG 兜底**(现状路径不变)。
- 验证: 4321(就绪)直开 iframe/收起回 SVG/Escape 关闭重开全通过; 4325(无 node)SVG 路径不变;
  `/api/health` 两态 spider_ready true/false 正确。

**命中行可读性**(用户反馈: `kb-xxxx·title` 不可读):
- `feed_events.details` 透传 `matched.title`(stats.py, 测试锁死);
- SVG 命中行显示**人类可读标题**(`hitLabel()`, 与 spider_export.label_of 同口径),
  完整标题+条目 id 收进 SVG `<title>` 悬停; 无标题的老 trace 回退旧格式 `id·hit_fields`。
- 守护测试 2 处: `spider_ready` 类型/缓存一致、details.title 透传。

## 10. 四轮改造: 播放坞(方案 B) + 克隆仓 chrome=none(同日)

**交互模型再变更**(用户看过 A/B/C 三布局原型后拍板 B): 回放从"模态遮罩弹层"改为
**main 内播放坞 `#dock`**(KPI 卡下方), SVG 弹层退居纯降级路线。

- **就绪态(spider_ready=true)**: 点条目 → 坞展开(不遮罩, feed/榜单仍可见), iframe 加载
  `previewUrl`(带 `chrome=none`, 默认自动重播+循环); 坞已开时点另一条目=**就地换 trace**;
  "✕ 收起"→ 43px 细栏(卸 iframe 省资源), **点细栏体秒重展开**(会话在 serve 端缓存);
  桥意外失败 → 坞隐藏, 自动降级 SVG 并在弹层头部提示错误。
- **不就绪态**: 坞全程隐藏, 点条目开 SVG 弹层(头部标注"蜘蛛桥不可用…已降级 SVG 动画")。
- **Escape 语义**: 先关 SVG 弹层, 弹层未开时收起播放坞。
- **serve**: `_embed_url()` 给 previewUrl 的 query 段追加 `chrome=none`(`#token` 片段不动,
  不进缓存键); 老克隆仓不识别该参数也无副作用。
- **克隆仓(prompt-spider-ui)**: `boot.js` 识别 `?chrome=none` → `body.chromeless`;
  `style.css` 复用 immersive 布局隐藏 topbar/inspector/transport/drawer, 画布占满视口。
- **守护测试**: `/api/spider` 断言 `chrome=none in previewUrl.split('#')[0]` +
  `{loop:true, action:"restart"}` 下发; pytest 276 全绿。
- **验证**: 4321 就绪态坞展开/换 trace/收起重展开/chromeless 画面(topbar 隐藏, 画布占满)/
  循环回绕/Esc 收坞 全通过; 4325 不就绪态坞隐藏、SVG 弹层+命中行标题正常、Esc 关闭正常。
- **环境陷阱(本仓多次踩坑)**: serve 启动时一次性读入 index.html, **改前端必须重启 serve**;
  重启前必须确认端口无残留旧进程(`Get-NetTCPConnection -LocalPort <p>` 逐个核对
  CommandLine 再杀), 并以 `dock in served HTML` 探针确认服务的是新代码。
  **杀进程正则必须是 `kb(\.exe"?)?\s+serve|kb\.cli\s+serve`**——PowerShell 列出的 CommandLine
  有两种形态: `"…kb.exe" serve`(exe 带引号)与 `"…python.exe" -m kb.cli serve`(模块形态),
  窄正则漏杀任一种→新进程绑不上端口、继续服务旧 HTML(六轮改造再次踩中 `-m kb.cli` 形态)。

## 11. 五轮逐屏回归(播放坞改造后, 同日)

**前置清理**: 全量枚举残留 serve(`Get-CimInstance Win32_Process | ? CommandLine -match
'kb\.exe serve'`)——发现 4321 上叠了**双进程**(同秒两份), 4325 上先后有两批旧代码进程
(即"服务旧 HTML"根因); 全杀 → 端口 0 监听 → 全新启动 → 三探针通过
(`spider_ready=True` / `dock in HTML` / `fullFrame 已移除`)后才开始走查。

| 用例 | 结果 | 关键证据 |
|------|------|----------|
| W1 加载 | PASS | ● 已连接; KPI 5 组有数(87.4%/95 次); feed 30 |
| W2 窗口 | PASS | 7天↔全部 KPI 变化(95→96 次) |
| W3/W4 视图 | PASS | 单项目 table 隐藏(offsetParent=0); 联邦 3 caller 矩阵显示 |
| W5 外接源 | PASS | ●tdbm title=ok; 堆叠 title `project:196(85%)/ext:tdbm:34(15%)` |
| W6 stale | PASS | tale-caller-x 行 STALE 类(09-30 活跃) |
| W7 下钻 | PASS | 点 flysee 行→横幅"已下钻到项目 flysee-video-web"; KPI 切 7 次检索 |
| W8 双榜 | PASS | 热门 TOP6 标题可读; 零命中榜带"追因→"; "已消化 ✅"标记正常 |
| W9/W25 追因 | PASS | 填 query+过滤到 1 条+无"没有匹配"误导 |
| W10 feed | PASS | dot g/r 色、query·ms·时间齐全 |
| W11 SSE | PASS | 注入"W11 实时注入验证"≤2s 出现在流首 |
| W12 过滤 | PASS | sse→1/7; 无匹配→`#feedEmpty` 引导文案; 清空复原 7/7 |
| W13 坞展开 | PASS | dock block、src 带 chrome=none、modal 不开、feed 仍可见 |
| W14 键盘 | PASS | tabindex=0; Enter/Space 开坞; Esc 先弹层后收坞 |
| W15 零命中 | PASS | 零命中条目也走坞(iframe chrome=none) |
| W16 换 trace | PASS | docks 恒 1, src 就地换 session, 标题同步 |
| W17 收起重开 | PASS | 收起→38px 细栏+iframe 卸载(about:blank); 点栏秒重开 |
| W19 空目录 | PASS | "trace / 目录不存在 — 观测尚未开启"横幅 |
| W20 token | PASS | `/` 401; `?token=t123` 200; 错 token 401 |
| W21 API | PASS | 6×200 + 未知 replay 404 |
| W22 ingest | PASS | ok:true / 400 / deduped:true |
| W23 稀疏 trace | PASS | 无 title trace → replay 200 且 `"label":"kb-…-a1b2"` 回退 id; 浏览器坞正常出 iframe。**注**: 注入最小 trace 必须带 `returned` 数组, 否则 0 事件(仅 configure/complete, 属预期语义) |
| W24 竞态 | PASS | 8 连切后终态一致; 14 条 console 全为测试驱动噪音(旧页签 ERR/EventSource ERR_ABORTED/驱动脚本笔误), 0 产品异常 |

**观察项(非缺陷)**: 矩阵下钻只改内存视图与横幅, 不重写 URL 的 `?caller=` 参数——刷新后
回到下钻前的视图。若需可分享链接语义, 后续可在下钻时 `history.replaceState`。

**测量教训**: feed 过滤是 `display:none` 隐藏而非移除 DOM, 断言可见数必须用
`offsetParent!==null`, 数 `.feed-item` 总数会得出"过滤失效"的假阴性。

**收尾**: 临时 serve(4322 token/4323 空目录)用完即杀并验证 0 监听, 防制造新残留。

## 12. 实现方案: 视图状态写入 URL(history.replaceState)(已实施, 实测见 §14 F)

**动机**(§11 观察项): `view/caller/win` 只存活于内存——下钻改 `caller` 不回写 URL, 刷新即丢;
链接不可分享(Grafana/Datadog 等观测面板均把关键视图状态放 URL, 见 §13 佐证)。

**状态↔URL 契约**(与现有 `callerParam()` 语义对齐):

| 状态 | URL 表示 | 缺省 |
|------|----------|------|
| 单项目(默认) | 无 `caller` 参数 | `caller=''` |
| 下钻单项目 | `caller=<repo>` | — |
| 联邦 | `caller=*` | — |
| 时间窗口 | `w=7\|30\|0`(0=全部) | `w=7` |
| token | 原样保留, 本方案不触碰 | — |

**实际落地代码**(`src/kb/web/index.html`, 共 4 处, 与源码同步):

```js
// ① 脚本头部: 启动恢复 + 同步器(单一真源 view/caller/win)
let caller=qs.get('caller')||'';  let view='single', win=7;
if(caller==='*'){view='fed';caller='';}          // caller=* → 联邦
if([7,30,0].includes(+qs.get('w')))win=+qs.get('w');   // 非法 w 回退 7
function syncUrl(push){
  const p=new URLSearchParams(location.search);   // 在现有参数上改 → token 天然保留
  if(view==='fed')p.set('caller','*');
  else if(caller)p.set('caller',caller); else p.delete('caller');
  p.set('w',String(win));
  history[push?'pushState':'replaceState']({view,caller,win},'',
    location.pathname+'?'+p+location.hash);
}
// ② render(push) 内统一调用: syncUrl(push); 下钻处 render(true) 入栈
//    (矩阵行 onclick → render(true), 浏览器返回键=回退下钻前的联邦视图);
//    视图/窗口切换 render() → replaceState, 不污染历史。
// ③ boot 末尾: history.replaceState({view,caller,win},'',location.href);
//    固化初始态, 保证第一条 popstate 有 state。
// ④ 前进/后退(以 URL 为准重新解析, 而非读 e.state):
addEventListener('popstate',e=>{const p=new URLSearchParams(location.search);
  view=p.get('caller')==='*'?'fed':'single';
  caller=p.get('caller')&&p.get('caller')!=='*'?p.get('caller'):'';
  if([7,30,0].includes(+p.get('w')))win=+p.get('w');
  render();});
```

**与初稿的两处差异**(实施时修正):
1. `popstate` 从"解构 `e.state`"改为**重新解析 URL 参数**——直接输入/分享链接进入的首条历史
   没有 state, 统一以 URL 为准可覆盖全部路径(state 仅作快恢复冗余);
2. `syncUrl` 不在各调用点手写, 收进 `render(push)` 统一出口——新增视图切换入口不会漏同步。

**注意**: `qs` 是启动时快照, `apiUrl()` 取 token 不受 pushState 影响(同文档 token 不变);
`syncUrl` 基于 `new URLSearchParams(location.search)` 增删, 未触碰的参数(如 `token`/`degraded`)
原样透传 → W26d 由代码结构保障(token 经下钻/切换后仍在 URL, API 不 401)。

**验收结果**(W26, 实测 §14 F): a 刷新复现 ✅ b 浏览器返回回联邦 ✅ c `w=30` 分享复现 ✅
d token 透传(结构保障, 闸门口径另由 W20 守护) ✅。

## 13. 使用者视角逐屏走查(截图取证, 同日) + UX 佐证

**业界佐证**: 观测面板应"降低认知负荷而非增加"(Grafana 官方仪表盘最佳实践);
流式组件(stream widget)应放在版面末端避免"困住滚动"(Datadog 集成规范);
关键视图状态编码进 URL 以支持分享/刷新复现是通行做法(state-in-URL 模式,
DevExpress 的 IncludeDashboardStateToUrl、react-router 等均内置)。
来源: Grafana docs "Dashboard best practices" · Datadog "integrations-core dashboard
guidelines" · kiboschool "State in URLs" · npm state-in-url。

**逐屏观察 → 优化建议**(按优先级):

| 级别 | 屏区 | 观察(实测) | 建议 |
|------|------|-----------|------|
| P0 | 检索流 | 条目命中仍显示 `kb-20261013-7737, …` 裸 id——与用户已反馈过的"SVG 命中行要可读标题"同源; `details.title` 后端已透传, 前端未用 | feedItem 用 `raw.details[id].title` 优先渲染(截断+title 悬停显 id), 与 `hitLabel()` 同口径 |
| P0 | 播放坞 | `chrome=none` 隐藏了克隆仓 transport——**用户失去暂停/进度控制**, 循环只能收起或换 trace | dockBar 加 ⏯ 按钮, 经 serve 代理桥发 `spider_control_playback {paused}`; 或坞 Esc 兼作暂停 |
| P1 | 播放坞 | 高 46vh(303px)下 landscape 画布两侧留黑、动画仅约 400×250, 文字难辨(与用户"尽量占用界面"诉求冲突) | 默认 60vh + dockBar 加 ⤢ 切换 90vh 沉浸档; iframe 高度让画布接近 16:9 满宽 |
| P1 | 视图切换 | 展开坞后切"多项目联邦", 坞仍占首屏, 矩阵被推出视口(实测 matrixTop=-1029) | `render()` 里视图/窗口切换时自动 `dockClose()`(细栏可秒回) |
| P1 | 全局 | 视图状态不写 URL(§12 方案待落地) | 按 §12 实施 W26a-d |
| P2 | 时间窗口 | "7天"无具体日期范围, 口径需脑算 | 窗口按钮 tooltip 显示 `since≈YYYY-MM-DD` |
| P2 | 榜单 | "追因→"仅 12px 小按钮可点 | 零命中整行可点(与条目标题同行响应) |
| P2 | 检索流 | 过滤框无键盘快捷键; 切换视图瞬间 feed 清空无骨架 | `/` 聚焦过滤框; loadFeed 期间显示 2-3 行骨架条 |
| P2 | 热门榜 | 标题 CSS 截断后悬停 title 只有 id(截图文案"悬停看 id") | title 改"完整标题 · id" |

**控制台 17 条判读(0 产品缺陷)**: 4325 连接拒绝 ×2=浏览器残留旧页签对已杀服务重试 SSE;
 `/api/stream` 与克隆仓 `/api/sessions/*/events` 的 ERR_ABORTED ×12=切视图/换 trace/导航时
 EventSource 与 iframe 被正常中断(浏览器网络层日志, 非 JS 异常);
 SyntaxError/TypeError ×2=测试驱动脚本自身笔误。**均无需修复**, 清掉残留页签即净。

**追加需求已落地(同日)**: ① 热门榜 TOP6→**TOP10**(标题+slice 同步);
② 面板所有时间统一为 **Asia/Shanghai 本地串直通格式 `yyyy/MM/dd HH:mm:ss`**(`fmtTs()`,
矩阵"最近活跃"/feed 快照/SSE 新条目三处; ts 本就是写入机上海时间, 不做浏览器时区换算;
SSE 条目原缺时间字段, 已补显)。

## 14. 四轮改造: 检索流分页 + 定宽对齐 + P0/P1 打包(已实施+实测)

**需求**: ① 检索流分页(页码条, 50/页); ② mono 行耗时定宽对齐; ③ §13 的 P0/P1 全量带上。

**改动**(全部单文件可回滚):

| 块 | 实现 | 守护/实测 |
|----|------|----------|
| A 分页 | `feedArr` 数组真源(新→旧, API 已排序**直存勿 reverse**——实施时曾误 reverse 致最旧置顶, W27a 抓到); `renderFeed`=过滤→切页→页码条(窗口≤5+首尾+省略号); `loadFeed` 一次拉 500; 过滤/换条件回页1; SSE 仅页1重渲染(读旧页不打断); 追因 drillTo 简化(500 条内直滤) | W27a `155/155·第1/4页·页1满50` ✅; W27b 翻页换数据 ✅; W27c 过滤回页1 ✅; W27d SSE 新事件落页1首条+`new` 动画 ✅ |
| B 定宽 | `.mono .dur{inline-block;min-width:5.5ch;right}`; 时间列 fmtTs 恒 19 字符 | W28: 50 行 `.mono` 右缘坐标**唯一**, `.dur` 实测恒 33px ✅ |
| C 可读标题 | `hitTitle/feedLabel`(标题截断 24 字, `details.title` 优先, 与 hitLabel 同口径); 悬停 title=`完整标题 · id`; `feedHay` 含标题(过滤可搜标题词) | W29: feed 显示`命中 W27实时条目标题-可读`, tip=`…-可读 · kb-20261013-7737` ✅ |
| D ⏯ 控制 | serve `POST /api/spider/<tid>/control`(token 同闸门, CTRL_KEYS 白名单过滤); 面板 dockBar ⏯, 换 trace 复位 | pytest `test_api_spider_control_proxies_and_filters`(透传/白名单503/未知404/无token401) ✅; W30b 点击→`▶`且桥收到 `{paused:true}` ✅ |
| E 尺寸避让 | 默认 46vh→**60vh**; ⤢ 切 90vh(localStorage `kb-dock-tall` 记忆); `render()` 开头自动 `dockClose()` 避让 | W30a 396px=60vh ✅; W30c 594px=90vh+ls=1 ✅; W17 切视图→43px 细栏+iframe 卸载→点栏秒重开 ✅ |
| F URL 状态 | §12 方案落地: `syncUrl(push)` 下钻 pushState/切换 replaceState; boot 恢复 `caller=*`+`w` 白名单; `popstate` 以 URL 为准复原三元组 | W26a 刷新复现联邦+30天 ✅; W26b 下钻→URL `caller=…`→**浏览器返回**回联邦 ✅; W26c 切窗口 `w=30` 可分享 ✅ |

**回归**: pytest **277** 全绿(+control 用例); node --check/py_compile 过。

**新增测试数据陷阱**: PowerShell `ConvertTo-Json` 发中文 body 会转码破坏(`?????`)——
造数注入改用**浏览器内 fetch**(UTF-8 干净)或 Python 发请求; 断言文案勿依赖 PowerShell 注入的中文。

## 15. 六轮改造: 回放整页化(取消 iframe 播放坞) + 时间轴逐条展开(已实施+实测)

**动机**(用户对照 preview.gif): 回放"太简单、蜘蛛像固定动作"。根因三条——
① gif 是克隆仓 **reference demo** 模式(20.92s 预设 175 词逐个扫描), 我们回放走 **live session**
模式, 布局本就不同; ② 导出时间轴把全部命中挤在 at=0.5/1.5 两点, 动画 1s 闪完只剩蜘蛛空转;
③ 2.5s 循环里 16s 周期的蜘蛛椭圆只走 1/6 弧, 观感=抖动+跳变。

**决策**(brainstorm 两轮确认): 取消 iframe 嵌入, 直接用克隆仓整页 session 视图(自带
transport/inspector); 只展开时间轴(不动克隆仓 livePose 周期); 总时长封顶≈14s;
新标签打开(固定窗口名复用); 词墙布局本轮不做(先看效果)。

**改动**:
- **面板** `src/kb/web/index.html`: 删播放坞全套(HTML/CSS/dockPlay/⏯/⤢/避让/Esc 收坞);
  `openReplay()`=手势内同步 `window.open('about:blank','kb-spider-replay')` 防弹窗拦截,
  fetch 到 previewUrl 后赋 `w.location`; 失败关标签回落 SVG 弹层(`_replayErr` 标注)。
- **serve** `src/kb/serve.py`: 删 `_embed_url()`(整页不需要 chrome=none)与
  `POST /api/spider/<tid>/control` 代理(transport 原生自带); `loop+restart` 下发保留。
- **spider_export** `src/kb/spider_export.py`: 逐条 stagger 时间轴——首条 at=0.5,
  `stag=min(0.6, max(0.12, 11/(n-1)))`, 每条 running→(+0.45)completed, 尾缓冲 2s;
  零命中/全 you 保持 2.5s 短轴。**关键坑**: stagger 下限(0.12)<fly(0.45)时下一条
  running 比上一条 completed 先到, 顺序产 log 会 at 倒退被对端 validateRecord 拒收 →
  必须按 (at, 同刻序) 排序后再编 revision。you 随首批落定, >99 溢出单独成批。
- **克隆仓** `app/boot.js`+`style.css`: 顶栏模式切换——session 视图注入「▶ 参考演示」(→`/`),
  demo 页有 `ps-last-session` 时注入「⟲ 回放上次会话」; token 靠 live.js 既有 sessionStorage
  回退, 同标签来回切换不掉线。chrome=none 能力保留(无害)。

**守护测试**: `test_timeline_staggered_not_all_at_once`(12 条 running 错开≥8 个时刻、
跨度≥6s、duration≤14.5、at 非递减、duration=末 at); `test_timeline_zero_and_all_you_short_loop`
(零命中/全 you=短轴且 you 仍入 log); spider 桥用例改为断言 previewUrl **不含** chrome=none、
`#token` 片段原样。control 端点用例随端点删除。**pytest 278 全绿**。

**实测(4321)**:
- 点流条目 → 新标签整页打开(固定窗口名), 标题"KB 命中回放 t-20261021-3219", transport 可见;
- 4 条命中 duration=4.75s, 播放位 2.10→0.96(回绕)→4.58 证明循环+新时间轴生效;
- 「▶ 参考演示」→ `/` demo 模式, 「⟲ 回放上次会话」出现; 点回 → session 视图,
  sessionStorage token 在、连接正常、位置连续(4.58/4.75 继续);
- 探针: served HTML `openReplay:true`、`id="dock"` 已消失、control 端点 404。

**测试驱动注意**: browseruse 的 `browser_tabs` 只列自己管理的标签组, 页面 `window.open`
的新标签不在其中——验证新标签内容时改为拿 previewUrl 直接 `browser_navigate(newTab:true)`;
evaluate 脚本里 `\\d` 等双反斜杠转义会被传输层吃掉, 用 `substring/indexOf` 替代正则。

## 16. 七轮改造: 回放浮层化 + 词墙布局(已实施+实测)

**动机**(用户): ① 新标签打断浏览, 要"浮于 main 上方的模块"; ② gif 里"蜘蛛爬在词上"的
词墙观感要可切换。决策: 大浮层+保留克隆仓原生控件; 默认词墙+可切回(只影响我们的回放)。

**改动**:
- **面板** `src/kb/web/index.html`: `window.open` → `#rp` 浮层(94vw×88vh 遮罩, iframe 加载
  previewUrl **原样**——原生 topbar/transport/词墙切换全保留)。细顶栏: trace 标题 +
  ⤢ 新标签(整页出口保留) + ✕ 关闭。关闭途径: ✕/Esc(先 SVG 弹层后浮层)/点遮罩空白;
  关时卸 iframe; 浮层开着点别的条目=就地换 src。
- **克隆仓**: `lib/config.js` layout 白名单 +`wall`; `live-layout.js` 新增 `wallArea()`
  (场景中部 62% 宽, 避开右缘分箱列)、`eventPlacement` wall 分支(3~4 行自适应多列网格)、
  `livePose` wall 轨道对准词墙区; `live.js` 顶栏「▦ 词墙/☰ 列表」切换钮(`ps-live-layout`
  偏好, 默认词墙; 只覆盖前端渲染视图**不回写会话配置**——他人真机会话不受影响)、
  布局下拉加词墙选项、aspectRatio 三分支重写(wall 落 16/9)。
  **关键坑**: 覆盖后的 config 对象必须按基准缓存同一引用——`syncConfig` 用
  `lastConfig===config` 短路去重, 每帧新建对象会击穿缓存导致输入框被反复重置。
- **spider_export**: config `layout:"wall"`(导入即词墙)。注意 normalizeConfig 会拒未知
  layout——克隆仓白名单必须同批升级(已同批)。

**守护测试**: `test_record_shape` 断言 `config.layout=="wall"`。**pytest 278 全绿**。

**实测(4321)**:
- 点流条目 → 浮层打开(标题=query, meta=trace+循环), iframe src 预览 URL 原样;
- 回放页 `data-layout=wall`、切换钮显示「☰ 列表」(默认词墙生效); 点击 →
  `landscape|list|▦ 词墙`(切回+偏好落盘), 再点回词墙;
- 4 命中 trace seek 到 4.0s: regions 4 个、2 列(x=168/503)2 行——词墙多列分布;
  截图确认蜘蛛轨道压在词墙区、右侧分箱/stream/stats 保留、transport 原生可用;
- ⤢ 新标签 / ✕ / Esc / 遮罩空白四种收口全通; 零命中 trace(0 events)regions=0 属预期。

**测试驱动注意(补充)**: `#token=` 片段在 evaluate 拼 URL 时易丢(token 空→live 报
"预览令牌缺失"回落参考演示)——先 `fetch('/api/spider/<tid>')` 拿完整 previewUrl 再导航;
`browser_take_screenshot` 的图在 `screenshot_uri` 字段, 用 Read 工具读该 jpg 看画面。

**词墙轨道错位修复(同轮)**: 现象=蜘蛛像在词墙空白处转圈。根因: `eventPlacement` wall 分支
行高 `ch=a.h/rows` 无上限, 事件少时行距被撑到 313px(4 事件两行), 词团上下只有两行、中间
一整片空白; 而 `livePose` 按固定 wallArea 绕大椭圆(ry=225), 大半轨迹都在空白带里。
修复(几何对准, 两处配套): ① 行高封顶 `ch=min(46, a.h/rows)`+顶部起排——词团紧凑如 gif;
② 新增 `tightBox(regions)`(本可见页词团实际 bbox), `livePose(...,tight)` 优先按词团定
轨道中心与半径(ry≥60 保底防压扁), 渲染器每帧在 regions 定稿后传入——翻页/过滤后轨道
随之收敛。实测: 行距 313→46px, tight=(168,212,629,70), 截图蜘蛛落在词行正中。
教训: **动画轨道要对准"内容实际在哪", 不能对准"区域名义多大"**——区域随数据量伸缩时,
固定几何必错位; 用可见内容反推 bbox 是通用解。

### §16 补充实测(B1/B2, 2026-10-21, 浏览器实测)

**B1 浮层"就地换 trace"**(serve 4321, `spider_ready=true`; iframe load 事件计数钩子验证
整文档重载, 只读观测不改页面逻辑):

| 步骤 | 断言 | 结果 |
| --- | --- | --- |
| 点条目 docker(`t-20261021-9a46`) | 浮层打开: 标题`▶ docker`、meta `trace t-20261021-9a46`、src=session f61ffdb4 | ✅ |
| 浮层开着→键盘 Enter 切 uvicorn(`t-20261020-ddb5`) | 标题→`▶ uvicorn`、meta→`trace t-20261020-ddb5`、src→session 6a954fdc(就地换, `rp.open` 全程未关); loads +2 = iframe 整文档重载 | ✅ |
| 换后 ~2s 截图 | iframe 内已是 ddb5 回放(页面标题/query 行/分箱 5 HITS 均与 ddb5 一致), 进度条位于最左 = 新会话**从 0 起播**, 无旧会话(docker 13.95s 循环)进度残留; 独立标签实测该 session 播放连续(1.42→5.00/5.35) | ✅ |
| 三切零命中 正斜杠 穿越(`t-20261020-0931`) | 标题/meta/src(session 53f8be69)全换; iframe 独立标签验证页面标题`KB 命中回放 t-20261020-0931 · 0 命中`, 画面无任何 docker/uvicorn 旧数据 | ✅ |
| Esc | 浮层关闭, frame src=`about:blank`(卸 iframe 语义在换 trace 后仍成立) | ✅ |

![换 trace 前(docker)](b1-switch-from-docker.jpg)
![换到 uvicorn 后 ~2s: 回放对象全换、进度条最左从 0 起播](b1-switch-to-uvicorn-t0.jpg)

**B2 降级路径(桥不就绪→SVG 弹层)**: 独立 4322 serve, 环境仅该进程内改:
`$env:PATH` 剔除 hermes node 目录(`Get-Command node` 已为空) + `$env:KB_SPIDER_HOME`
指向不存在目录 + `.venv\Scripts\kb.exe serve --port 4322`; 探针 `/api/health`
`spider_ready:false`。测毕按 PID 只杀 4322, 4321 复核仍 `spider_ready:true`。

- 点条目 → 打开的是 `#modal` SVG 弹层(`modalOpen=true, rpOpen=false`, 浮层未参与);
- 弹层头 `蜘蛛回放 · docker · agent-kb · 22ms · trace t-20261021-9a46`;
- 命中行为人类可读标题(`1. Docker Desktop 资源上限的真实来源与 Resource Saver 卡死…`),
  id 只作后缀/悬停, **非裸 kb-id**; 分箱计数 46 HITS(项目层 14)与 9a46 数据一致;
- Escape → 弹层关闭(`modalOpen=false`), Escape 分发(先 SVG 后浮层)在浮层版下正常。

![降级 SVG 弹层](b2-svg-degraded.jpg)

**偏离/注意**: ① 代码注释称"浮层开着点别的流条目=就地换 src", 但实测鼠标点击被浮层
遮挡未能到达条目(点击后状态不变、也不关闭); 就地换 src 分支实际经键盘到达
(feed 条目 tabIndex+Enter/Space, 与 click 同走 `openFeed`)且断言全通。鼠标可达性
是否要恢复(如浮层态下 feed 仍可点)留产品判断, 非本次回归。
② 4322 未带 `--repo`, 默认 kb_root 解析到 `E:\Workplace\Agent-KB`(同仓另一盘符挂载),
traces 一致, 不影响结论。③ evaluate 返回值经 `text()` 输出在部分调用里被序列化吞掉
(`[object Object]`/undefined), 改传纯字符串表达式后稳定——browseruse 踩坑补充。

## 17. 蜘蛛轨道缓动过渡(2026-10-21, 浏览器逐帧实测)

**现象**: 词墙回放里蜘蛛会"瞬移"——首词到达(t≈0.5s)词团 bbox 一变, 蜘蛛一步跳到新轨道;
翻页/切路由过滤时同样。seek 反而是唯一应该瞬移的场景(用户意图就是跳位)。

**根因一句话**: `livePose` 每帧直接按当帧 `tightBox` 解析式取位, 轨道参数(cx/cy/rx/ry)
随词团突变, 位置跟着突变。**修复**(克隆仓 `0a06636`+`4b756b5`): 轨道参数帧率无关指数缓动
`easeOrbit(k=1-exp(-dt/τ), τ=0.35)` + snap 兜底(首帧/reducedMotion/后台恢复 dt>0.5s/
位移>0.6 对角线)。

**实测数据**(`t-20261021-9a46`, query=docker, 46 命中 2 页, duration=13.95s, 词墙布局;
serve 4321 重启后, evaluate 以 ~50-60ms 间隔采样 `renderer.orbitPos`/`renderer.orbit`):

| 用例 | 采样 | 最大相邻帧位移 | 断言 | 结果 |
| --- | --- | --- | --- | --- |
| 首词到达(t 0→1.42s, 0.54s 首词出场, 轨道 cy 504→252 缓收) | 30 帧 | **37.2px**/66ms 帧 | <40px(瞬移应为 ~250px 一步) | ✅ |
| 翻页 page1→page0(t=7s 暂停态, 词团 bbox 变) | 21 帧 | **8.5px** | 连续滑移无跳变 | ✅ |
| 过滤 all→code(该 trace 46 事件 route 全为 code, 截图 code=46/model=0/ext=0, 过滤后可见集合完全不变) | 22 帧 | **1.0px** | 轨道不动, 蜘蛛仅沿轨巡游; 1.0px 属数据特性而非缓动证据, 缓动以 all→ext(133px)行为准 | ✅ |
| 过滤 all→ext(0 命中→回落 wallArea, cy 408→505 总位移 ~133px) | 27 帧 | **22.1px** | ~1s 内指数收敛, 无单步 133px | ✅ |
| seek 0.3s→13.4s | 32 帧 | **286px**(单帧) | 允许 snap 一步落位 | ✅ 且落位后位置锁定(后续帧 ±1px), 无长漂流 |
| 词墙→列表(wall→landscape) | 22 帧 | **34.4px**(首帧) | 允许 snap 但实测为缓动 | ✅ 34→24→17→14→…单调收敛, **无回抽振荡** |

首词用例关键序列(pos, 0.44s→0.54s 首词出场前后): `(759,552)→(753,516)→(750,494)→
(745,463)→…→(704,292)`——每步 ≤37px 连续滑移; 修复前此处应为 cy 一步 250px+ 的瞬移。

截图: 缓动中途(t=2.46s, 首批词刚出场、轨道仍在收)与落位后(t=13.58s, 轨道贴合 46 词词团):

![首词到达缓动中途](s17-firstword-mid.jpg)
![落位后轨道贴合词团](s17-settled.jpg)

**结论**: 首词到达/翻页/过滤三类突跳全部消除(逐帧位移 <40px 且随 τ 指数收敛);
seek 保留 snap 语义(一步到位、无漂流); 布局切换走缓动且无振荡。遗留: 极端场景
(可见页词团 bbox 差异大于 0.6 对角线)仍会 snap, 属设计内兜底, 未构造出该数据。

**测试驱动注意(补充)**: ① 回放浮层 iframe 与面板**跨端口**(57087 vs 4321), 父页 evaluate
读 iframe 被同源策略拒(SecurityError)——从 iframe src 拿完整 previewUrl(含 `#token=`)
直接 `browser_navigate(newTab:true)` 开独立标签即可 evaluate; ② evaluate 的 script 里
async/await 箭头链易被包装层拒("window is not defined"是发进了 Exec 沙箱), 统一
`function(){}` + `.then()` 链, 结果先存 `window.__S*` 再另行读取; ③ 计划指定的
`t-20261021-3219` 已不在 traces/(每日定时任务轮转), 用
`python -m kb.cli search --query docker --trace --repo .`(kb 不在 PATH, 本轮实测踩的坑)
现场构造 `t-20261021-9a46`(46 命中恰好 2 页, 覆盖翻页场景比原计划更充分)。

## §18 使用者视角新一轮走查(2026-10-21)

C1-C6 上线后以"第一次上手的用户"心智在 4321 全旅程走查(browseruse 实测), **未发现需修复的产品缺陷**:
首屏无 token 加载与 ● 已连接; C1 tooltip `起始 ≈ 2026-10-14(含当天往前 7 天)`、"全部"=不设起始日;
C2 点零命中行左段即追因(网关→1/10)且与按钮不双触发; C3 空白处 `/` 聚焦过滤框、框内输入 `a/b` 不被劫持;
C4 热门榜 title=`完整标题 · kb-20261012-…`; C5 条目 aria-label="打开回放: xxx"; C6 浮层右侧停靠与
main 零重叠、开着时鼠标点另一条目 src 就地更换(正斜杠→Windows→网关)、✕/Esc 关闭均生效; 回放画布
词墙+缓动轨道+控制条正常, 零命中 trace 蜘蛛稳定巡航; 状态过滤命中 3/7+零命中 4/7=全部 7 自洽;
URL 状态 `?w=7&caller=agent-kb` 刷新恢复窗口与下钻; 联邦视图 KPI/双榜/项目矩阵(命中率、活跃、
data-caller 下钻)正常。控制台仅切换会话时旧 SSE `net::ERR_ABORTED /api/sessions/<id>/events`
(预期 abort, 无害)。

## §19 打磨后回归走查(2026-10-21, commit 4a78064 后)

针对观感打磨(sticky header/动效/悬停态)做使用者回归, **无回归、无需修复**:
滚动 900px 后 header `top=0` 且线性渐隐底生效(截图确认无内容泄漏); 浮层入场 `rpIn` 动画挂载、
开着时点另一条目就地换 trace(src 更换、头部标题同步)、Esc 关闭(`.open` 类判定)正常; 追因
scrollIntoView 后 `#feed` 顶边 421 > header 底缘 51, scroll-margin 让位有效; 已读弱化
`[data-rd]`/hover 过渡/reduced-motion 三条 CSS 规则均在样式表在场; 联邦矩阵下钻
`caller=agent-kb` 后切窗口 `?w=7&caller=agent-kb` 两维状态互不踩踏; 重启 serve 后新加载页面
SSE 稳定 9s+ "● 已连接"。控制台仅两类预期噪声: 切会话旧 SSE `ERR_ABORTED`(主动 abort)与
旧标签跨 serve 重启的 `ERR_CONNECTION_RESET`(服务器重启复位存量连接, 非缺陷)。

## §20 窄屏与 reduced-motion 人工复核(commit 4a78064 后)

**窄屏(420px iframe 实测)**: 同源定宽 iframe(媒体查询按 iframe 视口生效)验证——`.boards2` 单列
(328.8px)、`.bar` 110/1fr/60 生效; 但发现既有缺陷: `.mono` 元信息 `white-space:nowrap` 不可收缩
(221-284px) 撑破 329px 容器, body 横滚 20px(scrollW 426 > clientW 406)。根因定位经排除法
(全部可见元素 right≤366 而 scrollW=426 → fixed/悬浮 → iframe 内 eval 枚举 scrollWidth>clientWidth)。
修复: `max-width:700px` 下 `.feed-item{flex-wrap:wrap}` + `.mono` 可换行右对齐;
复验 `sw=406=cw`、`#feed 329/329` 溢出消除, 截图确认换行观感正常。
**浮层窄屏回退**: iframe 内开浮层自动 `body.rp-center` 居中、`boxW=392 < vw=417` 不撑破。

**reduced-motion(机械化审计 + DevTools 人工复核)**: 枚举全部 8 个 @keyframes 与 4 处 transition,
审计发现 `.kpi`(border-color)与 `.seg button`(color/border/background)两处过渡未列入降级选择器,
已补入。人工复核(DevTools Rendering → emulate prefers-reduced-motion)按清单执行: 浮层直接出现
无滑入、条形瞬间成宽、悬停无位移动效, 用户操作回放浮层开/关流程正常。

## §26 第八轮走查: 真实路径与脏数据韧性(2026-10-21)

**发现并修复 3 个关联真实缺陷**(同一根因链: 读侧把 trace 文件当可信输入):
1. **聚合层裸崩**: `returned:null` 使 `len()` 抛 TypeError、`chars:"abc"` 使 `int()` 抛错——
   stats/feed/callers 三端点连接被直接掐断(无响应, 比 500 更糟, 面板只剩转圈)。
   直接调 `kb.stats` 复现: aggregate/feed/callers/by_source 4 函数 FAIL。
   **修复**: `trace._coerce()` 解析期归一化(显式 null→[]、非列表 returned→[]+告警、
   非数值 chars→None+告警; 语义脏值如负耗时/怪 ts 如实呈现不篡改)。
   注意缓存契约"入缓存后只读", 故归一必须在 `_parse_file` 解析时做(对象此刻私有)。
2. **watcher 单 tick 丢事件**: SSE 增量读对每行 `ev.get(...)` 无类型守卫, JSON 数组/标量行
    (`[1,2,3]`)会让 `_tick` 抛 AttributeError。`run()` 有兜底不会线程死, 但该 tick 剩余
    合法事件全部丢失(偏移已推进, 不再重读)——非对象行每出现一次丢一批。
    **修复**: `isinstance(ev, dict)` 守卫 + 与读侧同口径 `_coerce` 后广播。
3. **do_GET 只兜 BrokenPipeError**: 数据引发的异常裸穿→连接重置。**修复**: 追加
   `except Exception` 回 500 带错误体(面板可提示而非转圈)。
验证: 修复后 6 个聚合函数全 OK(3 条告警如实记录)、脏数据仓三端点 200、
watcher 在 3 条非对象行后仍存活(10/10→11/11 正常推送)、pytest 278 全过。

**深链直开**: `/?w=30&caller=agent-kb` 新页面完整恢复(30天高亮+单项目视图+下钻横幅)✅
**Tab 可达性**: 32 个交互元素按 DOM 序可达无重复; `:focus-visible` outline 规则覆盖
button/input/feed-item/bar; 自动化窗口无系统焦点致 `matches(':focus-visible')=false`
属测试局限(同 §19 reduced-motion 处理), 人工 Tab 复核可见焦点框。
**连续推送**: 阅读第 2 页时新推不打断(停留 page=2, DOM 保持 1 条)✅; DOM 恒定≤50(分页)✅;
翻回第 1 页新事件在顶带"新"态✅。已知微瑕(不修, 自愈): 旧页时 fcnt 分子用 `n+1` 近似,
连推 3 条显示 52/54(真实 54/54), 回第 1 页即恢复——轻量面板不值得为计数器加累计状态。
**zoom 200%**(CSS zoom 近似浏览器缩放): 页面无横向溢出(1078/1078);
榜单 span `sw>cw` 但带 `text-overflow:ellipsis+overflow:hidden`, 属设计内截断非缺陷。
**测试自我纠错×2**: ①推前数据仅 11 条不足一页, 点"第2页"按钮不存在导致误判"翻页被打断"——
读 onEvent 源码确认设计后补足数据重测; ②Exec 桥内嵌套引号转义 SyntaxError, 改转义写法。

## §25 第七轮走查: 数据边界与容错(2026-10-21)

用临时仓(`$env:TEMP\kb-walk7`, 独立 serve 4323)造极端数据, 不污染真实 traces/。
**发现并修复 1 个真实缺陷**: 超长查询(1200 字)整行渲染 → `.mono{white-space:nowrap}` 加上
无空格长串的 flex min-content 不可收缩, 把 `#feed` 撑出 **13681px 横向溢出**(页面 sw=13682 vs
cw=1000)。定位手法: 遍历 `#feed *` 找 `scrollWidth>clientWidth+2` 的元素, 一击命中
`.feed-item`。**修复**: 条目 query 展示统一截断 24 字(与既有 `feedLabel` 约定一致)+ 全文进
`title`(悬停看全); 复验 sw=cw=1000、页面 1078 无横滚, 截断条 `title` 长度=1200 全文可达。

**XSS 防护三探针全过**(数据含 `<script>` 赋值、`<img onerror>`、`<b>` 标签):
`#feed script` 节点数=0、`window.__xss`/`__xss2` 均未定义(payload 未执行)、
条目显示字面量文本——`esc()` 转义有效。

**脏数据容错**(jsonl 混入非法 JSON 行 / 空行 / 缺 trace_id 的对象): 服务端逐行 try 解析
静默跳过(`_parse_file` 的 bad line 分支), feed 正常返回有效事件, 页面渲染无异常。
**契约陷阱**: 首版造数据缺 `{"kind":"meta","schema":2}` 首行 → 整文件被 `read_traces`
判"缺 meta 首行, 跳过"(feed=0), 一度误以为服务端崩; 补 meta 行即恢复。造 trace 必须写 meta 头。

**海量与性能**: 603 条 → API 按 `limit=500` 截断(首条为最新, 新→旧正确);
空态附"仅载入最近 500 条, 更早记录请缩小时间窗口"引导(实测命中该分支);
翻到第 10 页 50 条渲染 11.3ms; 多文件(10-20 + 10-21)聚合正常。
**缺失 trace**: `/api/replay/t-not-exist` → 404 + `{"error":"trace ... not found"}`, 服务不炸。

**对比度抽查(WCAG AA)**: 背景 `rgb(13,17,23)` 下正文/链接 13.97、muted 6.45,
均 >4.5 阈值 ✅。

**走查自我纠错**: 一度以为"过滤框输入无效"(设 `#fquery` 后 `.empty` 仍 NO-EMPTY),
探测 DOM 发现实际 id 是 `#fq`——测试脚本用错选择器, 非产品缺陷; 改正后空态/500 提示正常。

## §24 第六轮走查: 访问控制与多标签并行(2026-10-21)

**发现并修复 1 个真实缺陷**: token 态下 `GET /` 面板首页也被鉴权拦截返回裸 JSON 401——
无 token 用户点开分享链接看到浏览器弹 `{"error":"unauthorized"}`, 前端专门的"需要访问令牌"
友好横幅(为 token 缺失场景设计)永远没机会渲染。**修复**: 静态壳 `/` 免鉴权(不含任何数据,
`/api/*` 与 POST 鉴权原样不动), 壳内 fetch 收到 401 后走既有横幅路径。
测试契约无"首页须 401"断言(test_serve_token_enforced 只测 /api/stats), 修复不破红线;
pytest 278 全过。**实测三路径**: 无 token→壳加载+友好横幅+骨架清理(skel=0);
错 token→同样横幅; 对 token→正常出数(12/12)+SSE 灯"● 已连接"(EventSource query 注 token 生效)。

**红线复确认**: `kb serve --bind 0.0.0.0` 无 token 直接拒启(exit=2, 中文红线提示)。

**多标签并行**(主标签 ?w=0&token + 同源 iframe ?w=7&token 两个独立会话):
- 状态互不串: iframe `w7` 按钮高亮、URL 保持 `?w=7`, 主标签保持 `?w=0`✅
- 浮层互不干扰: 主标签浮层开着(标题不变), iframe `rp` 独立关闭态✅
- 双推: CLI `--trace` 造一条新事件, 两页面 2s 内同时 12/12→13/13 顶部冒新条目✅
- 归因插曲: 首造数 `kb search --query` 未落 trace(该仓未开默认记录), 页面"没收到"并非推送缺陷——
  先取证 traces/ 最新时间戳排除服务端, 再查 cli.py 确认需 `--trace`/`KB_TRACE=1`/`.kb-trace` 标记;
  补 `--trace` 后双页面即收。教训: 双页面都"没动静"时先查数据源, 别先怀疑广播层。

## §23 第五轮走查: 导航韧性与回放控制(2026-10-21)

覆盖 pushState/popstate 落地后未测的历史导航、浮层×视图互扰、a11y 焦点归还、iframe 控制条, **全部通过、无缺陷**:
**历史导航**: 联邦→点矩阵行下钻(pushState 入栈, `?w=0&caller=agent-kb` + 横幅)→浏览器后退
(popstate)→回联邦 `caller=*` 且矩阵重新显示✅。
**浮层×主面板互扰**: 浮层开着切时间窗口(7天)与切视图(联邦), 浮层保持打开、rpTitle 回放标题不丢、
URL 状态正确联动(`?w=7&caller=*`)、feed 正常刷新✅——rp 独立于 render() 刷新路径。
**a11y 焦点归还(结论已纠错)**: 条目聚焦→Enter 开浮层→Esc 关→`document.activeElement` 回到原条目
(`isItem=true`)→再 Enter 还能开(键盘循环不中断)✅。**但根因不是"rpClose 实现了焦点归还"**
——源码核实 `rpClose()` 无任何 `focus()` 调用: 真实机制是开浮层时焦点从未移入面板(纯视觉浮层),
Esc 处理不移动焦点, 焦点原生停留在条目。~~已知局限: 若用户鼠标点浮层内 ✕ 关闭, 焦点落 body~~
 **已修复(增强项落地)**: `openReplay` 首次开层记 `rpLastFocus=document.activeElement`(换 trace
 不覆盖), `rpClose` 关闭时 `document.contains(el)&&el.focus()` 归还(幂等, 焦点本就在则无副作用)。
 实测: 原生聚焦条目→开层→✕ 关闭 → `activeElement` 回到条目(AE=DIV.feed-item)。
 归因附注: browser_click 自动化工具点击 div 不触发原生 focus(测得 AE=BODY 属工具假象),
 真实浏览器 mousedown 会给 tabindex=0 元素焦点, 合成 MouseEvent+focus 序列复现真实路径验证。
**回放控制条**(直接导航桥页面绕跨端口 snapshot 限制): 暂停后进度冻结(1.81→1.81)✅; 速度选
4×生效✅; 重播进度回绕(4× 下 1s 实时≈1.6 trace 秒, 数值合理)✅。
注: 桥 iframe 跨端口(59769≠4321), browser snapshot 不进入 iframe 内部, 控制条需直接导航桥
URL(从 `#rpBox iframe`.src 取)单独测——自动化方法论。

## §22 第四轮走查: 数据实时性与韧性(2026-10-21)

前三轮未验证过"实时命中流"招牌能力, 本轮端到端实测, **全部通过、无缺陷**:
**SSE 实时推送**: 浏览器开面板(10/10)→ CLI `kb search --query "SSE 实时性走查探针" --trace` →
3s 内页面实时冒出新条目(11/11, 首条 aria-label 即探针 query, 带 `new` 入场动画类)——watcher
(mtime+size 1s 轮询)→SSE→前端 unshift 链路真实工作。
**断线韧性**: 不刷新页面直接杀 serve → 连接灯 4s 内变"● 断连(重试中)"(红, pulse); 重启 serve →
EventSource 自动重连(页面零操作), 再 `--trace` 一次新事件照常到达(12/12), 灯回"● 已连接"。
**非法 URL 韧性**: `?w=-5` 回退默认 7 天(窗口高亮 7天); 未知参数 `zzz=<script>` 原样保留在
query 不解析不执行; `caller=../etc` 未命中 → feed 显示优雅空态("还没有检索记录…kb search"),
KPI 0 次, 无 JS 报错。注: 合法窗口零数据与非法 caller 零数据共用同一空态, 文案未区分场景,
可接受(追因落空同理)。
**sticky header 可读性**: 滚动中正文经过 header 底部 8% 渐隐带属设计内(模糊+渐隐), 截图复核
无阅读区残留遮挡。探针产生的 2 条 trace 留待每日定时任务自动提交, 不混入功能提交(AGENTS 红线)。

## §21 第三轮边角走查(2026-10-21, 键盘/状态边角/宽屏回归)

覆盖前两轮未压的边角, **未发现产品缺陷**:
**键盘路径**: 条目聚焦后 Enter 开回放✅; 浮层开着时 `/` 聚焦过滤框(停靠形态键盘通路, 与
"遮罩不遮检索流"设计一致)✅; Esc 关闭✅。**空格回放假象归因**: 自动化 `press_key(' ')` 插桩
捕获到 `e.key=''`(空串, 非 `' '`), 事件已到达 `#feed` 且 target 正确——浏览器自动化发键的 key
值缺失, 非产品问题; 合成标准 `KeyboardEvent(key:' ')` 后回放正常开启, 产品逻辑与 Enter 同一处理器。
**状态边角**: 已读计数点开回放后不变——归因 `data-rd` 语义源自 Agent `kb_show` 读全文的 SSE `get`
事件(feed 数据字段), "看过回放"本就不标已读, 符合设计; 过滤不存在词 → 空态"没有匹配的条目…" +
`0/10`✅; 30 天窗口切换 `?w=30` URL/高亮/计数联动✅; ⤢ 实现静态确认(`window.open(rpUrl)` 带空守卫,
新标签不入 browser_tabs 属已知测试环境限制)。
**宽屏回归**: 窄屏修复后 1088px 下条目仍单行(`sameLine:true`、`.mono` nowrap)✅。
控制台无新增错误。

**自动化方法论补充**: `browser_press_key` 对空格产生的 `keydown.key` 为空串——键盘逻辑涉及
非字符键/空格时, 用页内合成 `new KeyboardEvent('keydown',{key:' '})` 验证产品逻辑, 勿信自动化键值。

## §27 第九轮走查: 握手修复回归 + 桥进程死亡韧性(2026-10-22)

**主题**: 回归当日三笔回放握手修复(`d8cbf37` 标题即时落位 / `9961be3` 冷桥 20s+分段提示 /
`f430132` 代次守卫), 外加桥进程生命周期韧性。沙箱 4321, 探针 `rpSeq/rpAbort/20000/rpEverReady`
全在 served HTML。

**握手修复回归(全通过)**:
- W-R1 冷桥首导: 杀 node 桥+刷新页(rpEverReady 复位)→ 点击后 T0 同步读
  `meta=连接蜘蛛会话(首次拉起约十余秒)…`、`title=▶ <query>` 即时落位 ✅(注意: 导出快时
  完成文案会覆盖提示, 断言必须 click 同 evaluate 内同步读)。
- W-R2 连点竞态: 冷桥下 400ms 间隔三连点 A→B→C, T0 显 C 骨架+冷桥提示, 终态
  `title/meta/src` 全为 C、不降级、无误关 ✅——abort+seq 守卫真正丢弃在途响应
  (修复前迟到响应会把 src 覆盖回旧会话/迟到的失败会关掉用户正看着的浮层)。
- W-R3 步进 ◀▶: 按钮 disabled 边界正确(首条 prev 禁/末条 next 禁), Next/Prev 就地换
  trace+标题同步 ✅。按钮态在握手成功后才刷新(rpStepButtons 在成功尾部), 属设计内。
- W-R4 握手中关闭: open→立即 ✕, rpClose 的 `rpSeq++/abort` 作废在途握手, 8s 后
  rp 关、modal 不开、frame=about:blank(迟到响应不复活 UI)✅。

**发现并修复 2 个真实缺陷**:

| # | 症状 | 根因 | 修复 | 验证 |
|---|------|------|------|------|
| D-5 | 桥进程运行中途死亡(杀/崩)后, serve **余生**所有回放立即降级 SVG, 报 `[Errno 22] Invalid argument`, 重启 serve 才恢复 | `SpiderBridge._dead` 把"配置缺失永久短路"与"运行期进程死亡"混为一谈: 死管道写入抛 OSError→永久拉黑; 且 `_urls` 缓存的 previewUrl 指向死进程端口仍会命中返回 | `_dead` 仅在 `_mcp is None`(从未起桥成功)时短路; `p.poll()` 探活, 死桥 close+置 None 重 spawn, `_urls` 一并作废 | 浏览器实测杀桥→自动重连新桥(新 session/新端口, 无降级)×2 tid; 回归 `test_api_spider_revives_after_bridge_process_death` |
| D-6 | 零命中层若整键缺 `matched`(仿真脚本常规产出: 只记 repo/scanned/rejected), 点回放降级 SVG 报 `internal: KeyError: 'matched'` | `to_record` 裸取 `layer["matched"]`——D-4 同族漏网点, 这次漏的是**整键**而非子键 | `layer.get("matched") or []` | t-pg-41 实测修复后词墙浮层正常(0 命中短轴); 回归 `test_zero_hit_layer_without_matched_key` |

**沉淀**: `kb-20261022-66cc`(D-5 根因独立成条, accepted/verified/agent 留痕);
D-6 按红线并入既有条目 `kb-20261021-1b60`"新发现"段(同根因链不新建), index 重建无漂移。

**过程插曲(非缺陷)**: ① 冷桥首导 12s+ 令 browser_click 工具 60s 超时连带页面关闭——
改用 evaluate 内 `it.click()` 同步触发可绕; ② 步进钮一度疑似反转, 实为握手未完成时
`rpStepButtons` 尚未刷新+我误点两条目竞态, 读源码后按 tid 唯一性(0 重复)与终态复验澄清;
③ 控制台 7 条 ERR_CONNECTION_RESET/REFUSED 全为我杀桥/重启 serve 的预期噪音。

**回归**: pytest **282 全绿**(+2 新测试); 走查全程 0 未捕获 JS 异常。

## §35 第十七轮走查: 零命中周报正确性(消化判定)(2026-10-22)

**主题**: trace 链路自身正确性——`kb trace report`(零命中周报/消化率)是驱动团队补库
决策的数据源, 首次对"消化"语义做正确性断言。

**D-18 消化判定不分时间方向(实锤+修复)**:
- 探针: "css slash" 先命中(10-01)后失败(10-05, 条目被降级/删除的场景), 仍被标
  `digested=True` → 待消化榜漏掉"曾经能用现在失效"、最该补的词, 周报系统性高估消化率。
- 根因: 旧实现全量预扫命中事件建词表, 集合成员判定丢时序; "已消化"本质是
  "失败**之后**被解决"的方向命题。
- 修复: 命中事件按 (caller, ts, tokens) 留存, 每次失败只认 `hts >= ts` 的命中;
  同词多 caller 聚合用 **AND**(任一 caller 现状未解决就留榜, OR 会把 a 的消化误盖 b)。

**D-19 suggest 死分支(实锤+修复)**: `zero_hit_board` 读命中事件 `s.get("suggest")`,
但生产方 `build_search_event` **从不往任何事件写 suggest**(只活在 report/MCP 返回值)——
FR-3.2"按 suggest 改写后命中"消化路径**从上线起从未生效**。修复: suggest 透传进
**失败事件**(语义上建议词属于失败现场), 消费方改从失败事件读。教训: 跨模块 `.get`
读对方字段前必须 grep 生产方确认写入存在, `.get` 的宽容是断链的消音器(写 `s["suggest"]`
早 KeyError 暴露)。

**回归**: +3 测试(方向性/suggest 活路径/多 caller AND), pytest **296 全绿**。
中途自纠一次: 测试数据曾把"单 token 消化"方向写反(该语义是失败词为单词、命中 query
分词含之, 非拆失败词匹配), 属测试期望错非实现问题。

**沉淀**: 新建 `kb-20261022-d550`(消费方读生产方从未写入的字段+判定无时间语义;
accepted/verified/agent 留痕), lint/索引通过。

**走查法教训**: 指标类端点除了"数字对不对"(§29 口径), 还要攻"语义规则对不对"——
用生产/消费两侧代码对照真实事件样本, 专查消费方读了生产方从未写的字段(死分支)、
判定逻辑丢时序(已消化/已恢复/首次末次类词都是信号)。

## §34 第十六轮走查: MCP 面端到端(沉淀门控地基)(2026-10-22)

**主题**: 前 15 轮从未端到端走过 MCP 面(`mcp_server.py`, Agent 接入知识库主通道)。
本轮直取治理地基——红线 3"沉淀前查重、命中即更新"是否真拦得住。

**D-17 查重池看不见 draft, 同一知识可重复建草稿(实锤+修复, 高价值)**:
- 探针(同 body+同标题连调 `create_draft` 三次): 修复前**三条全部建成**(backend 下 3
  个文件), 中间夹 `kb index` 也拦不住; 两个 Agent 并发沉淀同一踩坑会双双通过。
- 根因(可见性范围错配): `_dup_hits` 只读 `index.jsonl`(live, 仅过审条目), 而 `kb_create`
  产的全是 draft 且**不进 live 索引**(进 draft 索引、也不进检索索引) → 查重池永远看不见
  任何 draft; 再叠加"刚 kb new 连 draft 索引都未重建"的时序窗口。后果被放大成**不可自愈**:
  重复 draft 不进检索索引, `kb search` 也发现不了, 人工无从去重。
- 修复: 查重池并入 `_draft_records`(扫源文件现算 `fingerprint`, draft 池小成本可忽略、
  无索引重建窗口); live 池仍用 index 预算指纹。
- 验证: 同探针修复后第二次即 `DuplicateCandidate` 拦下(仅剩 1 条), kb index 与否都拦。

**副作用即证据(重要)**: `test_review_session_cap_three` 用"Redis 池耗尽 独立验证0..9"
造 4 条 draft, 修复后第 2 条起被正确判重(共用 ≥3 字中文词组"池耗尽")——该测试把"主体相同、
靠序号区分"的取巧标题当独立条目, 正是被本次修复戳穿的**旧错误依赖**(旧世界 draft 互不可见
才侥幸通过)。改为真正独立主题后通过。教训: 修复暴露的"既有测试失败"要先甄别——这里是
测试数据本身不独立, 不是修复引入回归。

**MCP 面其余检查无问题**: kb_search 双层+外接源联邦/零命中 hint+suggest、kb_get 含
source:// 分流、kb_review draft→accepted 需 evidence+confidence 提升+单会话≤3 上限、
kb_create 强制 draft/speculative/project、kb_update 仅本项目 draft——红线契约齐备。

**回归**: 修 1(`test_review_session_cap_three` 标题独立化)+ 增 1
(`test_create_dedup_against_existing_draft`), pytest **293 全绿**。

**沉淀**: 新建 `kb-20261022-648d`(查重集合须覆盖尚未晋升的候选; accepted/verified/agent
留痕), 与 `kb-20261022-d8fb`/`kb-20261022-acc8` 结成"可见性范围错配"同族链。

**走查法教训**: 走查重/去重逻辑, 必须构造"两次写入之间的完整生命周期"探针(建→不 index
再建→index 再建), 而非只测"两个已发布条目互查"——本缺陷正是"写入落点(draft)与查重读源
(live)"错配, 只测 live 侧永远漏。

## §33 第十五轮走查: 双层联邦检索与路径参数契约(2026-10-22)

**主题**: 多仓联邦口径(双层检索 `--repo X --agent-kb Y`、层序优先级、逐层截断)与
CLI 路径参数语义。

**D-16 不存在的仓路径静默报空(实锤+修复)**:
- 探针: `search --repo <不存在路径>` → exit 0 + `[]`, 与"库里确实没有"**逐字节相同**;
  `--agent-kb` 层路径打错同样静默。对以退出码+stdout 决策的 Agent, 等于把"路径打错"
  报成"知识库没有答案"→ 跳过真实存在的知识。
- 根因: 索引加载层对"文件不存在"容忍返回 `[]`(设计正确, 内部层该容忍), 但 CLI 边界
  从不校验用户显式传入的路径 → "正常空结果"与"调用方错误"两类语义被压进同一输出。
  与 acc8(坏文件伪装成库无知识)同族: 症状层把故障层伪装成正常空结果。
- 修复: dispatch 收口统一校验显式 `--repo`/`--agent-kb` 路径存在性, 不存在 → exit 1 +
  `kb error: 路径不存在`; `init` 豁免(首次接入本就该允许目录未建, 由 init_repo 建骨架)。
- 验证: 修复后 exit 1 + stderr 可辨; 存在但空库的目录不误伤(仍 exit 0 + `[]`)。

**检查无问题**:
- 双层检索层序: `search_layers_report` 逐层取满即截断(spec §7 优先级语义), 层内
  score 降序、同分 index 序稳定; hit_fields/hit_spans 按 id 对齐透传 ✓;
- `get_layered` 按层序首个命中返回(项目层覆盖通用层的读取语义) ✓;
- `related_layers` 跨层按 id 去重 ✓;
- lint 跨仓指纹去重(cross_repos)已有专测。

**回归**: +1 测试(`test_cli_missing_repo_path_errors`), pytest **292 全绿**。
探针期间自我修正两处: ①探针 [3] 用错检索词层(docs 是项目层, 通用知识在仓根 kb)
误报"双层空", 复核后确认双层检索正常; ②回归测试注释把"空库不误伤"断言错写成
"init 例外", 已改正。

**沉淀**: 新建 `kb-20261022-d8fb`(CLI 契约: 空结果只有在输入合法时才有意义,
accepted/verified/agent 留痕), 参考段与 `kb-20261022-acc8` 互相引用成同族链。

**走查法教训**: 对 Agent 消费的 CLI, 每个路径/ID 参数都要试"传错了会看到什么"——
与正常空态不可区分即为缺陷; "内部层容忍缺失"与"边界层校验输入"是两件事, 别为了
后者去破坏前者。

## §32 第十四轮走查: 跨仓上提路径(export/promote)(2026-10-22)

**主题**: 红线 2 的落地动作"项目库→共享库"人工终审通道, 此前无任何端到端走查
(单测只测"文件到位+字段对", 不测检索面后果)。

**D-13 export 双向失联(实锤+修复)**: 搬移只动文件系统(write+unlink), 两仓
`index.jsonl` 均滞留——源仓 search 命中**已删条目**(断链), 目标仓 search **看不到**
新条目。根因: 检索只读派生索引, 而搬移动词漏了"派生物同步"不变量(且要同步两仓)。
修复: `export_entry` 成功后 `build_indexes()` 重建双方。端到端复核: accepted 条目
export 后目标仓命中/源仓除名, 双向 PASS。

**D-14 export 假仓黑洞(静态读码+复现+修复)**: `--to-repo` 打错路径时
`mkdir(parents=True)` 静默建假仓并完成搬移+删源, exit 0 报成功——条目从两仓双双消失。
修复: 前置校验目标 `kb/` 必须已存在, 拒绝时不删源不建目录。

**D-15 未审条目无警示直通(实锤+警示)**: draft/speculative 条目 export 原样搬入共享
库零提示。人工动作不硬拦(人有权带草稿), 但 stderr 醒目警示。

**甄别不修**: promote 原地改 scope 后项目仓 lint 报 `scope!=project must be promoted
to agent-kb`——这是 promote(建议)→export(落地)工作流的**待办信号**, 设计使然。

**回归**: +3 测试(假仓拒绝/双索引重建/未审警示), pytest **291 全绿**。
中途自我修正: 首个测试断言用 draft 条目→目标 `index.jsonl` 恒空(draft 不进检索索引,
设计), 改 accepted 后通过——沉淀"验证检索可见性必须用 accepted 条目"。

**沉淀**: 新建 `kb-20261022-6fd6`(accepted/verified/agent 留痕)。

**走查法教训**: 凡"操作 A 的结果要靠派生物 B 才可见"的系统, 走查必须查**操作后的 B**
(两仓索引), 不能只查文件落位; "目标路径是用户输入 + mkdir 兜底 + 删源"三连=数据黑洞
配方, 专挑路径参数打错一位来试。

## §31 第十三轮走查: 条目解析器对人手编辑文件的韧性(2026-10-22)

**主题**: 前几轮攻运行时(serve/浏览器/桥), 本轮回到**数据面**: `parse_entry` 按可信输入
对待人手编辑的条目文件, 实测单坏文件的全库爆炸半径。

**D-11 坏 YAML front-matter 全库瘫痪(实锤+修复)**:
- 探针(正常条目+缩进手滑条目, 跑 5 个子命令): 修复前 `lint/index/stat` 全 Traceback、
  `search` **静默空库**(exit 0 返回 `[]`)、`show` 连正常条目都 not found。崩溃点
  (yaml.safe_load)与症状点(search 说没有)分离——坏文件挡住 index.jsonl 重建, 下游
  检索把"库坏了"报成"库里没有"。
- 修复: `parse_entry` 捕获 YAMLError 降级 `fm={}`+`yaml_error` 字段; lint 对 yaml_error
  跳过 schema 校验直接报"文件名: front-matter YAML 语法错误: <原文>"(若只报"缺必填"
  会把用户引去补字段, 修错方向)。
- 修复后: lint exit 1 首错即病因, index/stat/show/search 全存活, 无辜条目可检索。

**D-12 带 BOM 条目静默隐身(排查干扰时坐实, 一行修复)**:
- PowerShell `Set-Content` 改写条目文件后 search 突然空——排查发现文件带 UTF-8 BOM:
  `read_text("utf-8")` 留下 `\ufeff` → front-matter 正则不匹配 → "无 fm"降级 →
  index 对无 id 条目**静默跳过**, 零告警。Windows 记事本/PowerShell 存盘自带 BOM,
  本机生态高频触发。
- 修复: `read_text("utf-8-sig")`(有 BOM 剥掉, 无 BOM 行为不变)。端到端实测:
  带 BOM 文件 index→search 全链路命中。

**检查无问题**: 全部写路径(save/new/gate/export)显式 `encoding="utf-8"`, GBK locale
下写坏中文的风险不成立; 非法 UTF-8 字节读侧会抛 UnicodeDecodeError——但 lint 同样
崩溃, 已评估: 该场景需要磁盘/同步工具损坏字节, 概率远低于 YAML 手滑, 暂不处理。

**回归**: +2 测试(`test_bom_tolerated`/`test_broken_yaml_degrades_not_crashes`),
pytest **288 全绿**。

**沉淀**: 新建 `kb-20261022-acc8`(D-11/D-12 同根因链合一条, accepted/verified/agent 留痕)。

**走查法教训**: ①数据面走查法 = "往库里放一个坏文件, 跑遍所有子命令看爆炸半径";
②探针自身也要排雷——本轮 BOM 缺陷正是**探针脚本用 PowerShell 写文件**时暴露的,
"排查环境干扰"的过程本身就是走查。

## §30 第十二轮走查: 实时流连接生命周期与 tail 韧性(2026-10-22)

**主题**: 前几轮均为单事件/单请求视角, 本轮攻**并发与连接生命周期**(SSE 订阅泄漏、
watcher tail 韧性、并发 ingest)。

**发现并修复 D-10 半行丢事件(实锤, 高价值)**:
- 探针(写方分两段写一行, 段间让 watcher 轮询落入): 修复前 SSE 只收到后续完整事件,
  半行事件**永久漏推**(文件完整, 刷新可见)——"实时漏一条刷新又回来", 用户极易误判偶发。
- 根因: `_tick` 读到 chunk 后无条件把偏移推进到末尾, 半行 JSONDecodeError 被 continue
  吞掉但偏移已越过 → 行补全后整体位于偏移之前, 永不再读。经典 tail 缺陷。
- 修复: 只消费到最后一个换行符, 偏移停行边界; 改**二进制读**统一 st_size/偏移/截断检测
  的字节口径(文本 tell 是 opaque cookie); \n 不在 UTF-8 多字节内部故按行截断解码必合法,
  CRLF 由 splitlines 剥 \r。
- 修复后同探针 PASS(tail-A/tail-B 都实时到达)。

**检查无泄漏/无新缺陷**:
- SSE 订阅泄漏: `_sse` finally unsubscribe ✓; 前端 `stream()` 先 `es.close()` 再重建,
  切视图/窗口不累积连接 ✓; 慢消费者断开走 BrokenPipe 分支正常退订。
- `seen_ingest` check-then-act 非原子(并发重发同 key 可双落盘): 已知不修——现实触发需
  同一事件在 timeout=1s 窗口内并发重发, 客户端无自动重试, 概率极低; 后果仅账本多一行,
  读侧按 trace_id 聚合可容忍。
- 多进程同文件追加: 单行写持 `_APPEND_LOCK` + O_APPEND, 行完整性成立(跨进程仅交错不撕裂)。

**回归**: +1 测试(`test_watcher_waits_for_complete_line`, 直接驱动 `_tick` 不依赖时序),
pytest **286 全绿**。

**沉淀**: 新建 `kb-20261022-1aaf`(tail 观察者偏移须停行边界, accepted/verified/agent 留痕)。

**走查法教训**: "文件当队列"的系统必须测**读写时序交叠**——把写方拆成两段写是通用手法,
任何"增量偏移+解析失败跳过"的观察者都在此暴露。修复前"刷新能看到"是重要线索: 说明
数据在、丢的是**消费进度管理**, 而非数据丢失。

## §29 第十一轮走查: 聚合口径一致性(2026-10-22)

**主题**: 前几轮全是功能面, 本轮首次对面板**数字正确性**做断言——时间窗口(7天/30天/全部)
是否真的作用于同屏所有数字。

**差分探针(沙箱注入窗口内/窗口外各 1 条同 caller 事件)**:
- **D-9 口径漂移(实锤, 已修)**: 切 7 天后 KPI=1 次检索, 同屏联邦矩阵同 caller 却=2
  (含 20 天前事件)。根因: `since` 只接进 `/api/stats` 的 KPI 分支——`/api/callers`
  根本不收该参数(前端也没传); `/api/stats` 里三个榜单用未过滤集计算, 而零命中榜空态
  文案自己写着"窗口内没有零命中"。单端点测试各测各的, **跨端点口径一致性**从无断言。
- 修复: `stats.in_window()` 统一入口(与 KPI 同 `_within` 口径), 矩阵统计列+三榜单全接;
  `/api/callers` 支持 `since` 并入缓存键; 前端 `loadMatrix()` 传窗口。
- **刻意保持全量的例外(实现内注释+测试锁住)**: 活跃性列(last_ts/stale)与外接源健康——
  掉线检测看最后一次真实活动, 过滤会把 8 天前活跃项目误报"从未活跃"; 矩阵行集取全量
  caller(窗口外行保留显 stale, 否则掉线项目整行消失); 窗口内 0 次 hit_rate=None 显"—"
  而非 0%。
- **浏览器 E2E 实测**: 7 天窗口 KPI"共 156 次" = 矩阵检索数列之和 156(win-probe 两侧
  同 1), stale-caller-x 行保留显"⚠ trace 掉线(>14d)"; 切"全部" KPI 158、win-probe 矩阵
  2, 反向一致。全程 console 无未捕获异常。
- 其他检查无发现: 聚合负数/None 输入在 §26 `_coerce` 已防; `callers()` 里
  `aggregate(searches,[])` 只取 by_caller 无消费率污染; 前端 `?w` 缺省的 `+null===0`
  陷阱当时已有守卫并有注释。

**回归**: +2 测试(`test_callers_window_consistency_with_kpi`/
`test_boards_honour_time_window`), pytest **285 全绿**。

**沉淀**: 新建 `kb-20261022-0d91`(筛选控件只接线一半端点同屏两口径, accepted/verified/
agent 留痕)。

**走查法教训**: 功能走查(点了有没有反应)与**口径走查**(显示的数字对不对、同屏互不
互相矛盾)是两类。口径类要专门设计"同一实体在 A/B 两处的数字必须相等"的**跨端点差分
断言**, 单端点自洽测试永远测不出"两处各对各的"。

## §28 第十轮走查: ingest 通道(2026-10-22)

**主题**: 团队态 ingest 上报口(带 token serve 4322 + 真实客户端代码路径中继)。W22 曾以
"合法/带 content 键/幂等"三点通过, 本轮把请求形态扩展后攻破红线实现。

**探针矩阵(API 级 + 落盘差分 + E2E)**:
- 幂等基线: 同事件重发 deduped ✅; **同 trace 换天 get 各入账一笔 = 正确语义**(每次读
  各记一笔, ts 是事件身份)——我初设期望"仍幂等"是错的, **D-8 撤回**;
- 键名红线: list 型 content 键拒 ✅、`Content` 大写键拒 ✅;
- **值误杀(D-7, 实锤)**: `query="content"/"text"/"body"`(合法检索词恰为红线词)全被
  400 拒, 而 `query="正文 content 规范"` 放行——实现对整坨序列化 JSON 扫 `"content"` 等
  子串, 值也扫, 命中纯看引号相邻与语义无关(PRD 原话是"正文**键名**拒收");
- **数据黑洞机制(两端闭合实测)**: 被误拒的事件经客户端 `append_event` 中继时,
  `_post_ingest` `except Exception: return` 静默吞 400(客户端零异常、账本 0 行、无任何
  告警)——"服务端误拒 + 客户端静默吞"组合 = 团队账本永久缺该事件且无人知晓;
- 64KB 上限: 实测最大事件行 ~2.8KB, 上限余量充足, 未见现实触发路径。

**修复(D-7)**: 红线改递归只查 dict 键名(`_has_body_key`, 含大小写变体), 值放行。
对照实验: 修复后 `query="content"` 经客户端 E2E 中继成功入账(1 行, 重发幂等仍 1 行);
嵌套 `layers[].matched[].content` 仍正确 400 且仍静默(静默语义按 PRD 保留)。
回归 `test_ingest_body_key_redline_checks_keys_not_values`, pytest **283 全绿**。

**沉淀**: 新建 `kb-20261022-7e9a`(红线校验作用域须与意图一致 + 误拒叠加静默吞的危险组合,
accepted/verified/agent 留痕)。

**走查法教训**: "合法/非法各一个代表样本"的 API 走查会漏掉**校验作用域错位**类缺陷——
红线样本(带 content 键)与放行样本(q=vite)都恰好不触碰错位面。要专门构造"**值恰为非法词**"
的合法样本, 以及嵌套/大小写/编码变体。静默旁路(尽力中继)的缺陷只能靠**落盘差分**
(声称接受 vs 账本实际)发现, 看 HTTP 响应和 console 都不够。

## §36 第十八轮走查: serve 鉴权面与矩阵口径可读性(2026-10-22)

**主题**: serve 鉴权面(token 校验路径、非本机绑定红线、静态壳免鉴权设计)+ 联邦矩阵
数字可读性。

**鉴权面(走查通过, 未见缺陷)**:
- `_authorized`: Bearer 头与 query token 双通道, 常量时间比较; 各 API 端点统一入口校验;
- `resolve_bind` 红线: 非本机绑定无 token 直接拒绝启动(与 json 条目"红线扫值不扫键"
  同族防线, 本轮复核实现与沉淀一致);
- `/` 静态壳免鉴权属设计内(壳不含数据, 数据端点全数受控);
- index.html 全部 innerHTML 注入点 esc 转义齐备(复核 §24 XSS 面未复发)。

**D-20 堆叠条百分比与命中率列分母不同基数(实锤+修复, 低危 UX)**:
- 探针: caller a 四次检索(2 次命中 3 条目 + 2 次零命中), 矩阵同行显示"命中率 50%"
  (分母=检索数)与堆叠 title"project: 2 次(67%)"(分母=命中条目数)——两数各自正确,
  但并排呈现诱导用户按同基数解读(50% 与 67% 看不出是两回事)。
- 与 §29(kb-20261022-0d91)同族: 那是数字互相矛盾(错), 本条是各自正确但缺口径标签
  (易误读)。按红线并入既有条目"新发现"段, 不新建。
- 修复: 堆叠条 title 自带分母口径"按命中条目构成(N 条): ..."。

**回归**: pytest **296 全绿**(前端 title 文案, 无新增后端断言); 浏览器 E2E 联邦页实测
title 显示"按命中条目构成(52 条): project: 52 次(100%)"等新口径文案, console 无异常。

**沉淀**: 并入 `kb-20261022-0d91`"新发现(第十八轮)"段, index 重建无漂移。

**过程插曲(非缺陷)**: 探针自身 conflict 判定条件写窄(要求占比恰=100%)导致 RESULT
误打 PASS, 但输出数据已足以证实口径现象——探针断言写窄不等于现象不存在, 以实测
输出为准而非探针结论。

## §37 第十九轮走查: 时间口径时区边界(窗口起日基准)(2026-10-22)

**主题**: 时间窗口全链路(ts 写入 → `_within` 日粒度比较 → 前端起日计算 → stale 判定 →
CLI `--since`)的时区基准一致性。承接 §36 同一大类(口径), 这次切的是**日期基准**维度。

**D-21 sinceDate 取 UTC 日与全库本地日基准混用(实锤+修复, 低危但每天规律发作)**:
- 全库日粒度均为本地日: `trace._now()` 写本地 tz 串(`ts[:10]`=本地日)、`callers` 的
  stale 用 `date.today()`、CLI `--since` 默认本地日——唯独前端 `sinceDate` 用
  `toISOString().slice(0,10)`(UTC 日)。
- 探针(浏览器页面上下文注入参考时刻, 非改系统钟): 上海 02:00 点"7天", 旧算法起日
  `2026-10-15`, 本地基准应 `2026-10-16`——**窗口多圈一天**, "近7天"实显 8 天;
  白天(≥08:00)新旧一致, 缺陷每天仅在 00:00–07:59(+08)发作, 白天走查天然看不见。
- 修复: `sinceDate` 改本地 getter 拼日期; 浏览器复验注入时刻返回 `2026-10-16`。
- 诚实记录(未彻底解决, 属面板既有设计): 面板刻意"以写入机时区为准不本地化换算"
  (`fmtTs` 注释), 跨时区查看者用本地日算 since 仍会偏。根治方案是起日由后端下发起日,
  前端不自算——记入条目"适用边界"段。

**D-22 时刻串按字符串比较, 跨偏移时刻序失真(实锤+修复, 团队态联邦场景)**(同轮补充):
- 顺着"日粒度切分"查下去发现更深一层: ts 还被**整串当字符串比大小**判先后。字符串序
  只在全体同偏移时等于时刻序——上海 `09:00+08:00`(=01:00Z) vs 纽约 `08:00-05:00`
  (=13:00Z), 字符串判上海晚, 真实纽约晚 12h。单机全员同偏移, 此 bug 只在跨时区成员
  上报后发作——正是团队态联邦的设计场景。
- 探针实锤三现场, 修复后全部翻转正确: ① `feed_events` 排序(且 limit 截断会丢真正最新
  事件) ② `by_caller.last_ts`/矩阵"最近活跃"(掉线检测基准) ③ `zero_hit_board` 消化方向
  (跨时区"失败后补库命中"被判未消化)。第 ④ 处 `_ext_health_latest` 同键顺手统一。
- 修复: 采集层唯一比较键 `trace.ts_key`(ISO→UTC 秒; 无偏移按写入机时区理解; 坏值退
  原文保证键可比), 显示仍用原串; `stale` 改 `_age_days` 时刻差, 弃"查看机本地日−
  写入机本地日"混基准相减。
- 插曲自纠两处: 探针第 3 项期望把消化语义写反(§35 是"失败词为单词、命中 query 分词
  含之", 我用了双词失败词)——改探针数据非改实现; 新测试首版 `tz(timedelta_hours=…)`
  参数臆造, 改回 `tz(timedelta(hours=…))`。

**其余时间链路走查通过**: `_within`/`by_day`/`cold_start`/CLI `--since` 均为"写入机本地日"
同一基准的日粒度比较(自洽, 跨时区查看者偏差已在 f55e 诚实记录为设计约束);
serve ingest 去重键用 ts 原串属身份比较非序比较, 不受影响。

**回归**: pytest **298 全绿**(+2: `test_timestamp_order_is_offset_aware` /
`test_stale_flag_is_offset_invariant`)。注意既有 296 条在旧实现下也全绿——它们全用
同偏移 ts, 正是"单机自测测不出跨时区缺陷"的镜像证据。

**沉淀**: 新建 `kb-20261022-f55e`(accepted/verified/agent 留痕, severity 由模板 medium
降 low——数据偏宽一天不影响决策方向); 双层 `kb search` 去重均无既有时区条目。D-22 与
f55e 同根因链(同一 ts 串的两种基准混用), 按红线**追加"新发现"段**到 f55e 而非新建;
去重时命中通用层 `kb-20261013-27e3`(epoch 固定 Asia/Shanghai 渲染)——结论方向相反的
同族条目, 已在 f55e 加 related + 专段辨析(展示要钉死基准 vs 比较要对齐数据基准)。

**走查法教训**: "按天规律性发作、与走查时刻强相关"的缺陷(时区/日切/星期几类),
在正常时段跑测试**永远绿**——必须用"注入参考时刻"主动构造边界时刻(凌晨/日切/月末),
不能依赖"刚好撞上"。本轮此前两轮(§36 口径标签)都属"数字正确但读错", 本轮是首次
"数字本身随观察时刻变错"——时间语义缺陷要按时间维度设计探针。

## §38 第二十轮走查: 条目生命周期面(待复核机制 + 状态机矩阵)(2026-10-22)

**主题**: 知识条目生命周期管理——`due_review` 待复核机制、状态机流转矩阵、
deprecated 治理。此前各轮都在"写入/检索/统计"面, 生命周期面(accepted 之后的事)未查过。

**撤回项(先记录)**: 初始假设"deprecated/superseded 是死胡同, 误判无法复活"——读
`docs/specs/2026-10-13-agent-kb-p1-design.md` §5.3 发现**终态是设计内决策**
("终态, 不可回迁(复活=新建条目并 related)"), 且检索面 deprecated 已被过滤+降权双防。
假设自我证伪, 不立缺陷。(顺带记录 spec 内部矛盾: §5.3 注"未核实的需…降 draft"
与矩阵 `accepted→draft` ✗ 冲突, 属文档笔误级别, 未改代码行为。)

**D-23 待复核机制自上线起空转(实锤+修复, 中高)**: `review_by` 消费链四件套齐全
(taxonomy schema→`due_review`→`stat`→CLI `--due-review`+AGENTS.md 工作流, spec §时效性
"到期进入待复核清单"), 但**全仓无任何代码写入该字段**——探针实测走完
draft→accepted(verified) 全流程 fm 无 review_by, `due_review` 放到 2030 年仍空,
`kb stat` 待复核数恒 0("知识库永远健康"的假阴性)。与 D-19(suggest 死分支)同模式:
消费方按设计文档形状写码, 生产方从未产出该形状。变体差异: 那边错数字, 这边**恒空
静默失效**——恒空的指标比错指标更难发现。
- 修复(生产链): `gate.review` 在 `to=accepted` 时落 `review_by = accepted日 +
  REVIEW_CYCLE_DAYS(365, 对齐 spec front-matter 示例 created→review_by 一年)`,
  人工显式设的未来值不覆盖、已过期值刷新(复核通过=再延一周期)。CLI/MCP 共用
  gate.review, 一处修复全端覆盖。
- 修复(存量缺口, 本条新维度): 补生产链只修增量——存量 accepted 无此字段, 且状态机
  禁 accepted→proposed/accepted, 它们**没有任何合法路径**再获得 review_by。消费侧兜底:
  `due_review` 对 accepted 无 review_by 时按 `updated + 周期`推导到期日。实测 2028
  视角 kb/ 200 条、docs/ 19 条 accepted 全部正确入账; 今天视角为空(未到期, 正确)。
- 通用判据: **给"新数据才有"的字段补生产链时, 同步问存量怎么办**——幂等回填或消费侧
  兜底二选一, 否则"修复只对明天生效"。

**回归**: +2 测试(`test_accepted_sets_review_by_cycle` 含 due_review 到期日出账断言 /
`test_accepted_keeps_manual_future_review_by` 不覆盖未来值+刷新过期值双分支),
pytest **300 全绿**。中途自纠两处: 测试编辑时误伤既有行(引号截断)即查即改;
第二测试首版用 accepted→accepted 刷新(状态机必拒)改双 proposed→accepted 分支。

**沉淀**: 双层去重命中 `kb-20261022-d550`(消费方读生产方从未写入的字段)——同模式,
按红线追加"新发现"段(含存量缺口新维度)而非新建, evidence 同步补留痕。

## §39 第二十一轮走查: promote/needs-scope-review 生命周期链(契约漂移)(2026-10-22)

**主题**: scope 上提建议链——promote(建议)→ needs-scope 待办清单 → set-scope/export
(终审落地)。承接 §38 生命周期面, 这次查"建议怎么变成落地"的交接处。

**D-24 promote 契约漂移: 建议型命令变成终审执行手(实锤+修复, 中高)**:
- 四处文档口径完全一致(AGENTS.md 红线2"只做建议, 由人 set-scope/export 落地"、
  README §4、spec §9 终审工作流、测试设定 C12"不改 scope"), 实现却立即改 scope +
  清 needs-scope-review。探针坐实两后果: ①刚发出的建议从 `--needs-scope` 人工待办
  清单消失(建议即终审, 人工确认环节被架空) ②scope 与物理位置错位(标 stack 躺项目仓,
  双层检索按 scope 过滤即错层)。
- git 考古定位引入点 `480cd0e`("promote reuses gate.set_scope write path"): 复用公共
  写路径时**继承了 set_scope 的终审副作用**, 且同一提交新增 `assert fm["scope"] ==
  "stack"` 把错误行为**当场固化进测试**——此后 CI 绿灯全在为漂移背书。
- 修复(三态分离): promote 只打标签(`promoted` + `promote-to:<scope>` +
  `needs-scope-review`, 不碰 scope; 重复 promote 改判目标不堆积); set_scope/export
  落地时经 `_strip_promote_tags` 清**全部**建议期标签(旧实现只清 needs-scope-review,
  promote-to 会永久残留)。建议目标用 tags 承载, 不动派生 schema(有 committed==derived
  测试锁)。

**其余面走查通过**: MCP server 无 promote/set_scope 暴露(agent 不能碰 scope, 红线2
工具面强制成立); export_entry 的 needs-scope-review 清理语义正确(export 本就是终审
落地动作); lint schema 对未知字段宽容(tags 自由数组可承载建议标签)。

**回归**: test_promote.py 按文档契约**重写**(旧断言正是漂移的固化物): 7 测试覆盖
建议不改 scope/留在待办清单/改判不堆积/落地清全部建议标签/枚举与 project 拒绝/
不改 status。pytest **302 全绿**。

**沉淀**: 新建 `kb-20261022-5b9a`(accepted/verified/auto-reviewed)——双层去重无命中,
新缺陷模式: "重构复用写路径时语义漂移"(与 648d/d8fb"消费面看不见"相反方向:
"执行面做多了")。判据: 复用公共函数逐项问"源函数每个副作用, 目标命令契约允许吗";
文档与测试断言冲突时先 git 考古哪个是原契约。

**插曲自纠**: 沉淀条目初稿手改 front-matter 为 accepted——违反门控一致性(应走
`kb review` 流转), 复原 draft 后经 review 命令正式流转成功。

## §40 第二十二轮走查: get 事件 trace 关联与消费率(猜测式外键)(2026-10-22)

**主题**: 消费漏斗最深处——get 事件如何关联回 search(_consumed_ids / consume_rate /
saved_chars_est 的共同地基)。承接 §22 trace 链路, 这次查"事件之间的边"。

**选题过程(两个面走查通过后落点第三个面)**: 外接源 source:// 编解码面——原生 id
含斜杠无歧义(前缀定长 + 分隔符取一次), Hit.make/get 往返一致, 通过; serve 静态与
回放面——`/api/replay/<tid>` 的 tid 只做字段等值比对不拼路径, 无目录穿越, 通过。
第三面字段对账时发现 latest_search_id 的关联策略与消费判定错配。

**D-25 get 尽力关联忽视手头强信号, 消费率系统性漏计(实锤+修复, 高)**:
- get 事件 trace_id = "该 caller 最近一条 search"(spec §4.4 原策略), 而消费判定
  _consumed_ids 要求"get 所在 trace 的 returned 含该 id"。序列 search A(返回 k1) →
  search B → get(k1): k1 挂 B 下, B 不含 k1 → 判未消费。探针实测 consume_rate 从
  0.33 掉到 **0.0**, saved_chars_est 归零——agent 真实工作流"连搜几轮再回头读"恰恰
  高频触发, 命中率越高的库漏得越多。
- 本质: kb_get(id) 的 id 就是精确匹配的外键(零成本强信号), 关联侧却用"猜最近"弱
  启发式; 关联不看 id、判定死盯 id, 两侧策略错配处即漏计。spec"尽力关联不追求
  强一致"方向没错但被过度兑现——"尽力"应是用尽可得信号后的兜底。
- 修复: latest_search_id 加 entry_id——优先"returned 含该 id 的最近一条", 匹配不到
  回退纯最近(外接源 id/手动 get 自然走兜底, 无需特判); MCP kb_get 埋点传 entry_id=id;
  spec §4.4 同步修订防回退。

**回归**: test_trace.py 单元(精确匹配优先/回退/不传参保旧语义) + test_trace_mcp.py
端到端(search 命中→零命中→get 首轮条目, 断言挂回首轮), pytest **304 全绿**。

**沉淀**: 新建 `kb-20261022-1256`(accepted/verified/auto-reviewed)——双层去重无
命中。通用判据: 写"尽力关联/模糊匹配"前确认更强信号是否真的不可得; 关联策略与
判定策略必须同源(判定盯 id, 关联就必须用 id)。

## §41 第二十三轮走查: 浏览器真实 UI 交互面(全项通过, 零缺陷轮)(2026-10-22)

**主题**: 前二十二轮多为"读码→探针"式走查, UI 交互细节靠 evaluate 读 DOM 间接验证。
本轮首次全程用浏览器真实交互(点击/输入/键盘/悬停)走查面板主流程, 逐项验证既有
修复在真实事件流下的行为。

**通过清单(全部实测)**:
- 视图切换: 单项目↔联邦(矩阵 12+3=15 与 KPI 自洽) → 下钻行 → URL `caller=agent-kb`
  + KPI 变 12(下钻过滤生效) + banner 提示
- 时间窗口: 7天→全部, KPI/URL `?w=0` 同步(§29 窗口联动保持)
- 状态过滤四态: 已读=1 行(恰为已读 uvicorn 那条) / 命中 / 零命中; 与文本过滤**叠加**
  正确(文本"sse-e2e-验证"+命中=0/12, +全部=3/12)——两维过滤独立且与计数一致
- 零命中榜"追因→": 跨组件联动正确(检索流过滤器自动填 query, 3/12 与榜上 ×3 相符)
- 回放浮层: 点击开启(#rp.open, iframe 载蜘蛛桥)、Esc 关闭、**焦点归还触发条目**
  (rpLastFocus 生效)、Enter 键盘回放(可访问性文案兑现)
- 悬停提示: 时间窗起始日、KPI 口径、条目标题+id、堆叠条"按命中条目构成(N 条)"
  (§36 口径标注在真实页面兑现: "project: 52 次(100%)")
- XSS: 含 `<img onerror>` 的历史探针 query 在按钮名/文本/title 三处全转义
- 追因后 fState.f='zero' 与按钮高亮同步(syncFseg)

**一次工具误报(非缺陷, 记录防再误)**: 用 evaluate 探测浮层可见性时选了泛化选择器
`#overlay/[class*=overlay]/[id*=replay]` 全未命中页面实际的 `#rp` 容器, 一度误判
"iframe 存在但浮层未显示"。逐层取 iframe 祖先链的计算样式后确认 `#rp.open` display
:flex 完全正常。教训: UI 断言选择器必须来自读码确认的真实 id, 不用猜测式泛选择器。

**结论**: UI 交互面(§24~§36 历轮修复的汇聚点)在真实浏览器下零缺陷。本轮不沉淀
(无新缺陷模式; "泛选择器误报"属走查工具用法, 记本档即可, 不入库)。

## §42 第二十四轮走查: 数据一致性——条目发现规则双定义(免检角落)(2026-10-22)

**主题**: 门控面(lint)与消费面(index/gate/query)对"哪些文件是条目"是否同一集合。
先排查通过面: lint 已有 duplicate id/related 悬空/supersedes 悬空/指纹冲突检测,
覆盖完备; 真实仓(kb/ 与 docs/kb/)当前均无散文件——缺陷是潜伏态而非活体。

**D-26 条目发现规则两套语义漂移, "进检索但免检"角落(实锤+修复, 中高)**:
- 盘点全仓 `.md` 扫描点共 **6 处、两种语义**: lint 走"第一层目录+排除点目录"
  (防挂载外仓, 有注释有理由), index/gate(查重/_find)/query(due_review/needs_scope)
  用 `kb.rglob("*.md")` 全量。
- 探针: kb 根直下 `loose.md`(坏 type+坏 status+缺 severity)与 `.mounted/` 外仓文件
  → **index 全收(可检索可消费), lint 对坏文件零报错**。schema/查重/占位段全绕过,
  门控"全库已校验"是假命题。
- 修复: `kb.entry.iter_entry_paths` 唯一事实源, 六读源全部改接; 回归测试断言
  "各读源可见集合必须相等"(结构性防漂移)。配套 `stray_entry_paths`: 统一后散文件
  从"免检"翻转"失踪"更糟, lint 显式点名"kb 根直下带 id 散文件, 请移入条目目录"。
- 通过面维持: 点目录外仓(设计内不可见)、生成物排除、INDEX.md 不 lint。

**回归**: test_lint.py +2(散文件点名+排除 / lint·index·gate·query 四读源集合一致性),
pytest **306 全绿**; 真实仓两处 `index --check` 无漂移、lint 通过。

**双向印证插曲**: 本轮沉淀自审走 `kb review --to accepted --as-agent`, 输出 front-matter
自动带上 `review_by: 2027-10-22`——第二十轮(§38)修的 review_by 生产链在本仓自己的
沉淀流程上首次实跑兑现。

**沉淀**: 新建 `kb-20261022-8b8f`(accepted/verified/auto-reviewed)——双层去重无命中。
通用判据: **门控说"全库通过"时, "全库"与消费方加载的集合必须同一函数算出来**;
两处枚举由不同人不同期写就, 默认当作已漂移, 先做集合差分。同族: d550(生产链归零)、
1256(关联与判定错配)——本条变体是"数据集合的边界"本身漂移。

## §43 第二十五轮走查: agent 沉淀闭环——写路径不同步派生索引(状态流转变体)(2026-10-22)

**主题**: 检索排序/截断面读码通过(scoring 权重、tie-break 稳定 index 序、跨层
取满即截断、truncated 账本恒等式, 均与 spec 一致)。顺藤深挖 MCP 沉淀闭环, 命中
D-27(检索核心读 index.jsonl 是引子)。

**D-27 review/set_scope 不重建索引, accepted 条目对检索+去重双隐身(实锤+修复, 高)**:
- MCP 端到端探针: `kb_create → kb_review(accepted)` 成功、源文件 status 已 accepted,
  `kb_search` 返回 `hits:[]`(scanned 0); 手动 `kb index` 后立即可见。draft 本就
  不在 live 池, accepted 流转是条目**首次入池**的开关, 而 gate 层没有踩这个开关。
- 最锋利后果(探针第 6 步): 刚 accepted 的条目**对去重也隐身**(live 池读 index.jsonl,
  §16 的 draft 池现算只认 status=draft)——再沉淀同主题条目查重不命中, **同一条知识
  被重复沉淀**, proj2 条目数 2。红线1"无需等人工"的闭环在最后一步断裂。
- 修复: `gate._reindex(repo)` 挂到 review 与 set_scope 落地处(repo_name 口径与
  cli `resolve().name.lower()` 一致), 对齐 export_entry 第十四轮先例。set_scope
  同修: scope 是 live 池过滤字段, 索引滞留旧值则双层检索错层。
- 元教训(记入沉淀"新发现"段): 第十四轮修 export 时先例只写在 export 注释里, 未
  升华成"所有改 live 池字段的写路径都要重建"的全局约束, review 照样漏。**修 A 处
  同类缺陷时把判据写进条目做全仓普查, 别只修触发处**; 判据补强: 改变派生索引所
  索引的字段值(status/scope/confidence)与改变文件存在性是同一类失真。

**通过面**: search.py 打分/排序/稳定 tie-break、layers 截断账本、CLI review 输出
不依赖索引——均无缺陷。探针插曲: 首版直接 `srv.call_tool` 不可行(需 memory session
官方 pattern); `iter_entry_paths` 返回 list 误用 next(); `await x()[:n]` 优先级笔误,
均已自纠。

**回归**: test_gate_write.py +3(即时可检索 / 去重免手动索引 / set_scope 刷新索引
scope 字段), `_mk` helper 补 title 参数, pytest **309 全绿**; 探针复跑步骤 4 即时
命中、步骤 6 isError=True 条目数 1。

**沉淀**: 命中既有条目 `kb-20261022-6fd6`(跨仓搬移不同步派生索引, 同根因家族)——
按红线追加"新发现"段(仓内状态流转变体 + 判据补强 + 元教训), 不新建。本轮 accepted
自审 0 条(更新既有条目不占额)。

## §44 第二十六轮走查: D-27 判据全仓普查——写路径与派生索引的完整对账(2026-10-22)

**主题**: 落实上轮元教训——不再等同类缺陷自己撞上来, 用 D-27 判据("改变派生索引
所索引的字段值的写路径必须重建")主动普查。方法: 先列消费方读哪些文件
(`query._records` 读双索引 / `search._load` 读 live / `gate._index_records` 读 live),
再反向列改这些事实源的写路径, 两表相减找漏网。

**D-28 普查命中 4 处同类洞(实锤+修复, 中高)**:
- `create_draft`: **最尖锐**——`get_entry`(kb_get/kb_show 底座)只读两个索引文件,
  探针实测"kb_create 返回 id → 立即 get_entry"返回 not found, `stat` 的
  total/draft_backlog 双双 0(漏计)。MCP 工具面 create→get 基本动作对自己刚建的
  条目失效。
- `update_draft`: title/body 改后 draft 索引滞留旧值(summary/dedup_key 派生自它们,
  去重指纹与展示失真)。
- `promote`: 打 `needs-scope-review`/`promote-to:*` 标签后 live 索引 tags 滞留,
  kb_search tag 过滤/面板列仍见旧标签。
- CLI `kb new` 非门控路径: 建 proposed(进 live 池)不重建, `kb new` 后立即 `kb show`
  同样 not found。
全部挂 `_reindex` 收口; 普查后写路径↔索引消费方**完整对账无遗漏**。

**回归**: test_gate_write.py +3(create 即时可读+stat 入账 / update 刷新 draft 索引 /
promote 刷新 live tags), pytest **312 全绿**; 探针复跑三连全正。

**沉淀**: 继续追加 `kb-20261022-6fd6`"新发现"段(普查落地记录 + 普查方法本身:
消费方读的文件 × 改这些事实源的写路径, 两表相减即漏网)。元教训闭环示范: §43
写下"别只修触发处"→ §44 照做并全中, 判据可执行性得到验证。

**探针插曲**: promote 误从 gate 导入(实际在 promote.py)、`to_scope` 关键字笔误、
walrus 误用于 mkdir 链——均为探针脚本自身问题, 自纠后一次跑通。

## §45 第二十七轮走查: 接入面 bootstrap——doctor index fresh 与生产端口径漂移(2026-10-22)

**主题**: 26 轮未碰的第一触点面(`kb init`/`kb doctor`)。init 侧读码通过:
去绝对路径的相对解释器、kb_dir 骨架、submodule 降级、仓外 --agent-kb 拒写、
token 只进用户级 conf——均与 FR 一致; `.mcp.json --repo-name` 取业务仓名是设计内
(trace 的 caller 归组语义), 与 index.jsonl 的层来源名(载体目录)是两个不同概念。

**D-29 doctor index fresh 恒误报 stale(实锤+修复, 中)**:
- 探针构造业务仓标准结构 `myproject/docs/kb/`(git init): `kb index --repo docs`
  按 CLI 默认口径写 repo="docs", 但 doctor 的 fresh 检查用 `biz.resolve().name`
  (=myproject)重算期望 → **恒 WARN stale**; 且按 WARN 建议的命令重建(仍是载体名
  口径)永远消不掉——"照建议做完还是红"的死循环。接入第一天就打击信任。
- 隐蔽性: 主仓 kb 恰好载体=仓根(两口径同名), 开发自测全绿; 既有 doctor 测试
  恰好都不断言 index fresh 项——面覆盖盲区与主仓同构盲区叠加。
- 修复: doctor 取名表达式改与 CLI 默认口径一致(`kb_base.resolve().name.lower()`),
  注释锚住"必须与 kb index CLI 默认口径一致"。

**通过面**: doctor 其余各项(venv/门禁依赖/submodule 悬空/lint/hook 新鲜度/.mcp.json
解析+绝对路径告警)逻辑与级别恰当; `_biz_root` git toplevel 回退链合理; 面板矩阵
by_source 按层序归类不涉 repo 名比对, 不受影响。

**回归**: test_bootstrap.py +1(CLI 口径构建后 doctor 必须 PASS, fixture 复用既有
fake_layout——它恰好就是业务仓 docs/kb 结构, 此前没人用它测过 index fresh),
pytest **313 全绿**; 探针复跑 doctor PASS, 主仓两态(自身/docs)均 up to date。

**沉淀**: 命中 `kb-20261022-8b8f`(同概念两套规则, 同族)——追加"新发现"段: 漂移
不只发生在"集合的枚举", 还发生在**比对所用的参数**上; `check(A, name=X)` 与
`build(A, name=Y)` 只要 X/Y 来自不同表达式即缺陷, 哪怕 X==Y 碰巧成立。

---

## §46 第二十八轮: spider-live 直播桥(第十二轮修复的第二份拷贝未同步)

**选题**: 观测面剩余未覆盖的 `spider_live.run` 增量读取循环。读码即警觉:
它与 serve TraceWatcher 是同款 tail 模式, 而 §30 修复只落在 serve 一侧。

**D-30 半行永久漏播(实锤+修复, 高)**:
- 探针(假 SpiderMcp + 真 run 线程)喂半行再补全: 修复前 `offsets[f]=fh.tell()`
  (文本模式)推进越过未写完字节, 行补全后 create_session=0——该事件在直播流
  **永久漏播**; 修复后补播=1。第十二轮同款缺陷在第二份拷贝里潜伏十六轮。
- 修复: 对齐 serve tail 语义(二进制读 + `rfind(b"\n")` 截行边界 + 偏移只推进到
  `pos+cut+1` + 截断重置)。

**D-31 历史 trace 每次启动全量回放(实锤+修复, 中)**:
- 拷贝时顺手复用 `t0 = time.monotonic()` 做首见文件 birth 判定:
  `st_ctime >= monotonic` 是 epoch 秒与 monotonic 秒跨钟系比较, 恒 False →
  既有"启动前文件只记偏移不回灌"的设计语义完全失效, 每次启动历史全量回放
  (会话洪泛)。serve 侧用 `time.time()` 一直是对的。
- 修复: 分离 `birth = time.time()`; t0 仅留 max_sec 超时用途。

**D-32 脏事件崩直播(实锤+修复, 中)**:
- `_dispatch` 未经 `_coerce` 归一: `ext:null` / `returned:null` 直接 TypeError;
  run 循环无逐事件防护 → **一条脏行让直播进程整体崩退**(serve 的 §26 修复同样
  没同步过来)。修复: 分发前过 `kbtrace._coerce` 同口径归一 + `_dispatch` 外
  逐事件 try/except; `event_to_updates` 三处 `get(k, [])` 改 `get(k) or []`。

**通过面**: `_dispatch` 的 get→you 分支只动 active 会话不新建, 迟到 get 不炸;
`COMPLETE_AFTER_SEC` 定格逻辑与 has_hits 判定合理; find_spider_home 候选链清晰。

**回归**: test_spider_live.py +4(半行补全后必须补播 / 历史文件不回灌 /
毒事件后续播 / null 字段不抛), pytest **317 全绿**; ruff `--select F,E9` 顺带
清掉 spider_live 死 import sys 与测试文件未用导入。

**沉淀**: 新建 `kb-20261023-463c`(accepted/verified)——D-28 判据的反向情形:
修一处模式缺陷时先按**代码指纹** grep 全部拷贝再定修复半径; "复制粘贴的模式
不会随原件一起进化", 且拷贝时的顺手改造(混用 monotonic/wall-clock)会引入
原件没有的新缺陷。

---

## §47 第二十九轮: userconf 用户级配置面(手写编解码对两侧契约不对称)

**选题**: 观测面外围从未覆盖的 `userconf.py`(~/.kb/config.toml 手写最小子集,
团队令牌/地址的落盘口)。读码即见疑点: 写侧恒 `key = "值"` 原样嵌入, 读侧却
`v.split("#")[0]` 无脑截注释——写读契约不对称。

**D-33 引号语义缺失, 凭据静默损坏(实锤+修复, 中)**:
- 探针三例全中: 含 `#` 的 URL 片段(`…/#board`→`…/`)、含 `#` 的令牌(`a#b#c`→`a`)
  写读往返被截断; 手写 `url = "http://h/x#y" # 注释` 引号内 `#` 也被当注释剥。
- 对称面快检再中一发: 值含 `"` 时写侧原样嵌入产出 `token = "a"b"` **损坏文件**。
- 失败模式最恶劣处是**静默**: token 尾巴被吃后请求照发, 401 无从排查。
- 修复: 读侧双引号值 `r'"((?:[^"\\]|\\.)*)"'` 匹配(闭引号跳过转义对——朴素
  `find('"')` 会被 `"a\"b"` 提前闭合, 修中二次实锤)、闭引号后仅容空白/`#`
  注释(旧损坏文件 `"a"b"` 尾段 `b"` 判坏)、单引号字面量、无引号值才剥 `#`;
  写侧转义 `\` `"` 与读侧单遍反转义严格互逆(两步 replace 对交叠转义会错序,
  三次实锤改单遍); 坏文件 ValueError→read_config 整体降级空, **绝不半解析**。
- 存量兼容: 旧版写坏的文件落入降级路径返回 (None,None) 回退单人态, 不再
  半解析出截断凭据。

**D-34 stats._ts_key 死拷贝遮蔽导入(ruff F811 抓获, 清理)**:
- 全仓 ruff 扫描顺带暴露: 第十九轮把 ts_key 上移 trace.py 后, stats.py 留了
  一份逐行相同的本地 def 遮蔽了 `from .trace import ts_key as _ts_key`——
  无用户可见缺陷(实现一致), 但正是"同源副本迟早漂移"的现场。删副本让导入
  生效; conftest.py 死导入 `datetime` 一并清。

**通过面**: serve_target/ingest_target 环境变量优先级清晰; 写侧项目仓零凭据
红线守住(只写用户级文件); `# 注释` 整行/段头解析正常。

**回归**: test_stats_serve.py +4(含#值往返/手写引号+行内注释/值含引号往返/
存量损坏降级), pytest **321 全绿**; ruff `--select F,E9` src+tests 全仓通过。

**沉淀**: 新建 `kb-20261023-c769`(accepted/verified)——D-28 同源判据在
**编解码对**上的形态: 序列化器与反序列化器不从同一格式规范派生, 每个边界
字符都是静默地雷; 自检 = 含全部边界字符的 `read(write(v)) == v` 往返测试。

---

## §48 第三十轮: kb new 的 id 分配面(两个唯一键只保了一个)

**选题**: 从第二十九轮"写入点契约"顺势走到创建路径本身——`new_entry.create_entry`
的 id/路径生成。读码即见不对称: 路径有完整 `while exists → -2/-3` 去重循环,
id 是 `secrets.token_hex(2)` 抽完直接落盘、零校验。

**D-35 id 静默撞车(实锤+修复, 中)**:
- 探针 mock 恒同值随机源: 两条同日条目静默双写同 id, 路径被 `-2` 掩盖毫无
  异常信号; `_find` 只命中第一个, 另一条 show/review/related/export 永久断链,
  只有事后 lint 才追溯。4 hex 空间 65536, 同日 N=100 生日悖论约 7.6%。
- 根因双层: ①"唯一性"心智里等于"文件名不冲突"——被去重保护的恰是可变的
  次键(slug), 权威主键(id 不可变)裸奔; ②概率分配被当确定性分配。
- 修复: `_unique_id` 撞了换下一个随机值重试, 连续 64 次才抛 RuntimeError;
  占用集合按 front-matter **id 内容**筛——首版按文件名前缀过滤被自纠推翻
  (slug 可人工改名, 文件名是日期段的代理指标, §42 同族), new 低频动作
  全量解析换正确性。

**通过面**: `_unique_path` 的 -2 循环对同题/纯中文标题(kebab 空→id 后 4 hex
兜底)工作正常; lint 的 duplicate id 兜底检查保留(但不能作主防线)。

**回归**: test_new.py +2(恒同值第二条必抛/改名同日条目仍在占用集合)+ 既有
中文去重测试并入"同日两条 id 必须不同"断言, pytest **323 全绿**; ruff F,E9 通过。

**沉淀**: 新建 `kb-20261023-c9c8`(accepted/verified)——实体 ≥2 唯一键时逐个
问"写入点谁在强制它"; 靠"概率不撞"或"事后 lint"的键都是缺陷; 加宽键降概率
不能替代写入点校验。

---

## §49 第三十一轮: launcher(kb web)拼 URL 面(编解码对判据第二形态)

**选题**: launcher.py 是观测面最后一块未走查的拼图(FR-2.5 发现链: 团队探活/
降级横幅/代拉起)。读码即疑: open_panel 的 URL 全靠 f-string 拼接、零百分号
编码, 而消费端是浏览器 URLSearchParams——与第二十九轮 userconf 完全同构的
"写读各自为政"。

**D-36 query 值不编码, 特殊字符静默损坏(实锤+修复, 中)**:
- 探针四例全中: token 含 `+` → 前端解成空格(`s3cr+tK=`→`s3cr tK=`, 面板全
  401); 含 `&` → 劈成两参数(token=`a` + 野生 `b=c`); 含 `#` → 整段降为
  fragment(token=`a`); 降级横幅 serve_url=`…/#board` → 横幅地址截残。且
  第二十九轮刚让 `#` 能合法进 config.toml——**同一份值流经的每一对编解码
  边界都要各自成立**, 文件侧修好不等于 URL 侧通。
- 附带洞: team_url 自身可带 query/fragment, 旧拼法把新参数落进 fragment
  全丢。修复: `_join_qs` 走 urlsplit/urlunsplit, 原 query 原样保留、新参数
  `quote(v, safe='')` 追加、fragment 丢弃(面板状态全走 query)。
- 甄别为设计内: 降级链本机 serve 由自己拉起不带 token(`kb web` 无 token
  参数), 非缺陷不修。

**通过面**: 同文件 grep 无其他 query 拼接点; 前端 apiUrl(callerParam/stream)
拼的都是已解码再 encodeURIComponent 的值, 链路语义正确(232/233/376 行)。

**回归**: test_stats_serve.py +3(团队链 token 含 `+&=#` 往返/降级链
serve_url 含 # + caller 含空格往返/_join_qs 边界), pytest **326 全绿**;
ruff F,E9 通过。探针自纠一处: 首版端到端断言把"降级链无 token"误判为缺陷,
读 CLI 面后确认设计内。

**沉淀**: 命中 `kb-20261023-c769`(编解码对契约, 同判据)——追加"新发现"段:
URL query 是同判据的第二形态, 读侧规则更严(浏览器语义); 自检 = 含全部保留
字符的值跑 `parse_qs == 原值`, 且解析器必须与真实消费端同语义(# 截
fragment、+ 解空格), 否则验证脚本自己就把真损坏判成 OK。

---

## §50 第三十二轮: 逐屏走查(真实 serve + 真实浏览器, 掩盖性数据全家桶)

**选题**: 前一轮 UI 走查(§41)用的是干净数据, 本轮反着来——专造掩盖性数据
(超长 query / XSS 字符进 query·项目名·suggest / null 字段爆炸 / 跨时区对 /
search→get 配对 / 迟到孤儿 get / 中文长项目名 / 极端 duration), 起真实 serve
逐屏实走: 联邦 KPI/榜单/矩阵、实时流、下钻、回放 modal。

**D-37 `layers: null` 打崩 /api/stats(实锤+修复, 高)**:
- 后端第一发就中: `layers: null` 事件使 `top_consumed` 的
  `s.get("layers", [])` 抛 TypeError → `/api/stats` 500(与 §26 的
  `returned: null` 完全同构)。`.get(k, [])` 的默认值对"键存在但为 null"
  不生效; stats 消费方一半写 `.get(k, [])` 一半写 `or []`, 口径不一。
- 修复走解析期统一净化(而非消费方逐点补防): `_coerce` 把
  `layers/ext/suggest/read` 与 returned 同批归零(显式 null→删键使下游默认值
  生效; 非列表→剔除+warn)。§26 当年名单只列了 returned 一个字段——净化器
  名单要对着 schema 全量列, 不能对着事故增量列。

**逐屏通过面(浏览器实测)**: XSS 零注入(`onerror` 载荷全部转义为文本,
injectedImg=0)、超长 query 不撑破横向滚动、KPI/矩阵/榜单数字与手算一致、
跨时区对排序正确(纽约 13:30Z 顶/上海 01:30Z 底, §37 修复在真实浏览器生效)、
search→get 配对(read 关联+consumed=1+saved_unknown 保守口径设计内)、矩阵
下钻(beta 行→URL caller=beta、feed 收敛 1 行、矩阵隐藏)、回放面板对
layers 缺失事件容错(标题/meta 正常)、console 除 SSE 切换正常 abort 外零报错。

**探针插曲**: 首版伪造 get 事件用了臆测字段(`entry_id/found`), consumed=0
一度像缺陷——对照 `build_get_event` 真实 schema(应为 `id/ok/chars`)后确认
是测试数据错, 修数据后消费链全对。**伪造事件前先读生产侧构造器**, 与 §48
"读 spec 再定罪"同谱。

**回归**: test_trace.py +1(全列表字段归一 + 三消费方不再 TypeError),
pytest **327 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c`(修复半径普查判据)——追加"新发现"段:
拷贝的第三种形态 = "同一净化名单只列了一个字段"(字段维度); `.get(k, 默认值)`
对键存在值为 null 不生效, 不可信输入应在进缓存前一次净化。

---

## §51 第三十三轮: sources.py 外接源连接器装配面

**选题**: FR-6 外接源层从未独立走查(只在 MCP 联邦测试里被顺带经过)。读码即疑:
`build_connectors` 用 `if "demo" in wanted` 对 `KB_SOURCES` 整串做子串匹配。

**D-38 开关子串匹配, 反向配置反而启用(实锤+修复, 中)**:
- 探针: `KB_SOURCES=notdemo`/`nodemo_nowiki`(意图=排除)→ 装配 `['demo']`,
  外部内容混进 agent 联邦检索。故障方向不对称: 误开=注入面, 误关=没数据。
- 修复: 逗号切分精确 token 匹配(lower/strip 保留, 未知 token 忽略前向兼容)。
- 全仓 grep `in wanted` 同款指纹仅此一处, 修复半径闭合(D-28 普查法)。

**D-39 search(limit) 契约拧巴(实锤+修复, 低)**: `max(1, min(limit, 20))` 把
limit≤0 抬成 1(远程连接器真发一次网络请求)再由 `[:limit]` 截空——结果碰巧对、
路径错。修复: ≤0 直接零命中不触后端; 非数值回退默认 5。

**通过面**: Hit.make 摘要 300 硬截+标注; 故障静默降级+health 记录; TDBM
分隔符归一/refs-ref 字段(真机联调 schema)回归在位; 凭据只从环境读红线守住。

**回归**: test_sources.py +2(装配精确匹配含正反例/limit 契约含触后端次数断言),
pytest **329 全绿**; ruff F,E9 通过。

**沉淀**: 新建 `kb-20261023-358e`(accepted/verified)——判据: `in` 的左操作数
若是"名字", 右操作数必须是集合而非拼好的字符串; 有分隔符就必须先切开再判断。

---

## §52 第三十四轮: serve /api/ingest 团队上报写面

**选题**: 第十轮只走了 ingest 的"正文键名红线"读侧误杀面, 写面本身的字段
类型契约从未探针。读码发现幂等 key 元组直接取 `ev.get(...)` 构造, 无任何
类型校验。

**D-40 身份字段类型不设防, 写侧崩或投毒(实锤+修复, 高)**:
- 探针三连: `trace_id=list` → 幂等 key 构造 TypeError → handler 线程崩、
  连接重置(§26 家族首次现于**写侧**); `caller_repo=dict` → 写侧 200 照收
  落盘入账本, 读侧 `by_caller.setdefault(dict)` 把 /api/stats 打崩 500——
  "写侧宽容、读侧崩"是账本系统最坏组合(污染持久、崩溃复利); `ts=dict` 同族。
- 修复双轨(执行 §50 判据且比上次完整): 写面对 schema 全量六字段
  (`trace_id/id/caller_repo/layer/source/ts`)非 str 即 400 fail-loud; 读面
  `_coerce` 同批净化**存量**脏文件(删键+warn, 降级"项目未知")——入口拒收
  只管未来, 存量净化兜底旧账, 缺一条腿都残留 500。

**通过面**: 无 token 401、正文键名红线(键不查值)、kind 白名单、64KB 上限、
幂等 dedup、ingest=False 防中继成环——第十轮修复面回归全绿。

**回归**: test_stats_serve.py +2(写面四字段拒收+正常不受牵/存量脏文件读侧
净化三消费方不再炸), pytest **331 全绿**; ruff F,E9 通过。插曲: SearchReplace
误删既有测试 docstring, 下一步立即恢复。

**沉淀**: 命中 `kb-20261023-463c` 追加新发现段——账本型系统类型校验必须写在
入口, 且**入口拒收与存量净化成对出现**; 只有前者=旧账继续崩, 只有后者=新账
继续进。

---

## §53 第三十五轮: front-matter 列表字段消费面(query/search/stat/related)

**选题**: 检索 filters 边界面。读 `_filtered_out` 见 `domain not in rec["domain"]`
——`in` 对字符串是子串。疑点: front-matter 手改把列表写成标量会怎样。

**D-41 列表字段退化 → `in` 变子串, 假通过/假命中/字母计数(实锤+修复, 高)**:
- 探针三例: `domain: frontend`(标量)→ `search(domain="front"/"ront")` 均假
  通过; `related` 标量 → `related("kb-…-aaa")` 截断 id 假命中(反向链接出现
  不存在的邻居); `Counter(…for d in r["domain"])` 把 frontend 拆成
  `{'f':1,'r':1,'o':1,…}` 字母计数, stat 安静地错。
- 隐蔽点: schema 校验能报(not of type array), 但**门控报了 ≠ 消费链安全**——
  读路径照常失真(存量文件/绕过 lint 的写入)。
- 修复(§52 判据第三次完整执行): `parse_entry` 单一入口 `_normalize_lists`
  对 schema 全量列表字段(domain/tags/related)归一——标量→单元素列表、null→
  删键、脏元素剔除; 退化记 `Entry.list_degraded` 由 lint 显式点名(归一让
  schema 看不到病因, 净化器必须与点名器成对, 否则"修复让问题隐身")。
- schema 核对: domain/tags/related 为 array, supersedes/superseded_by 本就是
  string|null——`_LIST_FIELDS` 恰好只列前者, 边界正确。

**回归**: test_entry.py +3(标量归一+退化记录/null 与脏元素/消费链端到端
filter 精确+stat 不再字母分解), pytest **334 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加第四形态——列表字段与 `in` 共生的系统,
解析入口就要把"可能是标量"的输入归一成列表; 故障形态从崩溃升级为静默错答。

---

## §54 第三十六轮: export 跨仓上提面(主键判据的跨仓形态)

**选题**: `kb export` 是 D-35(本仓 id 唯一性)判据天然的跨仓延伸点。读码见
冲突检查只有 `dst.exists()`——路径由可变的 slug 派生, 主键 id 无检查。

**D-42 export 只查路径碰撞, 同 id 不同 slug 长驱直入(实锤+修复, 高)**:
- 探针: 目标仓已有同 id(slug 不同, 模拟"早前从别的项目上提过")时 export
  成功 → 目标仓同 id 双条目、`_find` 只命中一个另一条断链; 且 export 是
  **破坏性搬移**(src 已删), 事后 lint 才发现=两仓回不去。
- 修复: 搬移前遍历目标仓条目(`iter_entry_paths` 唯一事实源)按 **id** 比对,
  同 id 即 GateViolation 拒收且不删源——主键校验对象是主键本身, 不是它的
  派生投影(路径)。

**通过面(读码+既有回归)**: 目标仓无 kb/ 拒收不建假仓(§32 修复在位)、
同 slug 路径冲突拒收、to_scope=project 拒收、未终审条目警示不拦(人工有权
带草稿)、source.project 保留已有值、双方索引重建(§32)。

**回归**: test_gate_write.py +1(同 id 不同 slug 拒收+不删源), pytest
**335 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-c9c8`(D-35 主键判据)追加跨仓形态——同一主键的
每一个写入路径(新建/导入/合并/搬移)都要各自强制; 破坏性写入的校验必须在
删之前, 拒收不得留半状态。

---

## §55 第三十七轮: spider 导入/导出面(净化器与硬索引消费方的暗雷)

**选题**: spider_export(回放 record 转换)与 spider_live(直播映射)是 trace 事件
的重度消费方, 从未做过脏事件专项。读码即见大量硬索引(`g["id"]`、
`search_ev["trace_id"]`、`l["repo"]`、`m["id"]`)——§52 净化器"删键"策略下全是
雷。

**D-43 净化删键 × 硬索引消费方 KeyError(实锤+修复, 中)**:
- 探针: get 被删 id 键 → `g["id"]` KeyError; search 被删 trace_id →
  `search_ev["trace_id"]` KeyError——回放屏整个掐断。修复: to_record 全链
  降 `.get`+isinstance 守卫(matched 子项/层对象本身都防), 缺键条目跳过、
  坏层过滤; spider_live.event_to_updates 同族同步。
- 判据(净化家族第五句): 净化器选"删键"策略时必须普查全体消费方硬索引
  访问并降 `.get`——改形状的那一刀要同时清点所有读这把形状的手。

**D-44 query 非字符串打崩 stats 榜面(实锤+修复, 中)**: `_coerce` 名单缺
query——`query: 123`(agent 查"123"被 JSON 数值化)让 `top_queries` 的 Counter
键 TypeError(list 时)、`zero_hit_board` 的 `.strip()` AttributeError。修复:
标量转字符串保留语义(检索词不是身份字段), 容器删键。§50"名单对 schema
全量列"欠的最后一块补上。

**回归**: test_spider_export.py +1(四段脏事件容错)、test_trace.py +1(query
类型净化+两榜不再炸), pytest **337 全绿**; ruff F,E9 通过。插曲: 测试自己
先炸出主循环漏过滤非 dict 层——测试也是探测器。

**沉淀**: 命中 `kb-20261023-463c` 追加第五形态——删键策略与硬索引消费方的
普查义务; 尽力呈现型消费方宜"置默认"而非"删键"。

---

## §56 第三十八轮: MCP 工具参数边界面(防线不等厚与误导性自解释)

**选题**: mcp_server 是 agent 的主写入口, 六工具参数从未做值域专项(CLI 面
的参数防御靠 argparse, MCP 面经 FastMCP JSONSchema 只有类型没有值域)。读码
对比两面即见 `severity` 一字段 CLI 有 choices、MCP/gate 零校验; kb_search 的
limit 直接进漏斗无归一。

**D-45 severity 枚举只在 CLI 面设防(实锤+修复, 中)**:
- 探针: `kb_create(severity='blocker')`/`kb_update(severity='紧急')` 均落盘
  并写进 draft 索引, lint 事后才报 schema 违规——索引污染已发生。
- 修复: `gate._check_severity` 挂 `create_draft`/`update_draft` 头部(所有
  入口共用的最后一跳), 枚举读 taxonomy.yaml 不抄字面量; CLI choices 保留
  (服务 --help 提示), 两处语义同源。
- 判据(净化家族第六句): 同一数据契约的守门强度按**最弱合法入口**对齐;
  枚举/类型校验放共用写函数入口, 不是各入口各写一份。

**D-46 kb_search limit≤0 产出自相矛盾的误导 hint(实锤+修复, 中)**:
- 探针: `limit=0/-3` 返回 `"scanned 1: 死于过滤器 0, 死于词匹配 0; 建议用
  更短单 token 重试"`——两死因皆 0 却建议改词, 真相是名额为零根本没扫出
  机会(旧实现每层 take=0 但 report 照扫全库)。
- 修复: `layers.search_layers_report` 漏斗归一(int() 容错/上限 100/≤0 截零
  短路不扫库, report 全零); MCP 面零名额直接返回"名额为零, 未执行检索"
  如实 hint; CLI 面同吃漏斗修复。
- 判据: **带自解释的输出会放大上游契约缺陷**——上游必须如实区分"没查到"
  与"没去查"; 数值参数的值域契约只能由被调方自己守(JSONSchema int 不拒负)。

**回归**: test_mcp.py +2(零名额如实 hint/严重度两面拒收+合法值可用)、
test_layers.py +1(limit 契约四路: 0/-3 不扫库、'3' 容忍、'abc' 回退),
pytest **340 全绿**; ruff F,E9 通过。

**沉淀**: `kb-20261023-463c` 追加第六形态(入口防线不等厚)、
`kb-20261023-358e` 追加 limit 契约洞在检索漏斗的重现(误导性自解释形态)。

---

## §57 第三十九轮: related 反向链接/发现通道面(隐藏承诺只装了一条通道)

**选题**: related 图面从未做可见性专项。读码发现 `query.related` 底座
`_records` 读 live+draft **双池**(反向环需要 draft 行), 而红线1 承诺"draft
不进检索"只落实在 search 单通道上——第二条发现通道(kb_related/MCP)裸奔。

**D-47 draft 条目经 related 双向泄漏给 agent(实锤+修复, 中)**:
- 探针: accepted 甲 `related:[草稿丙]`(正向)+ 草稿乙 `related:[甲]`(反向环
  带出乙行), `related(甲)` 返回两条 draft 的完整索引行(标题+摘要+path),
  同库 `search` 命中里 draft 干净缺席——同一承诺一面守一面漏。
- 修复: `query.related` 邻接行剔 `status==draft`(正反两环都堵); self 可为
  draft(人工 `kb related` 问自己的草稿, 邻人照报); get 面不动(已知 id 的
  读取面, 非发现面)。
- 判据(净化家族第七句): §56 的读面镜像——**多出口的过滤按同一承诺对齐**;
  每加一条"从不可信池读全量再输出"的通道都要回头补过滤, 宜下沉共享谓词
  `visible(r)` 让承诺只写一次。

**回归**: test_query.py +1(正向 draft 邻居剔除/self 为 draft 邻人照报),
pytest **341 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加第七形态(发现通道不等厚, §56 的读面
镜像)。

---

## §58 第四十轮: CLI 参数解析/错误路径面(值域不设防的两种静默故障)

**选题**: CLI/serve 参数面此前只吃过"路径不存在"(§15)与枚举 choices 两类
教训, "值域"(负数/非法格式)从未专项。读码圈定 `trace list --limit/--since`
两条字符串/切片运算参数。

**D-48 trace list --limit 负数切片翻转(实锤+修复, 中)**: 探针 5 条事件喂
`--limit -2` 返回 3 条(全量减 2)——`searches[:-2]` 的"去尾"语义。修复:
`read_traces` limit≤0 一律零名额, None 才"不限"(§51/§56 同族第三处)。

**D-49 非法 --since 静默滤空+周报假绿(实锤+修复, 中)**: `--since 2026-13-99`
让 list 显示"暂无记录" exit 0; `kb trace report --since 垃圾` 输出"零命中已
全部消化 ✅"假绿。修复: argparse `type=_date_arg` 入口拒收(exit 2), serve
API `since/until` 同步校验 400(面板假空态同族)。库层不净化——§52 原则:
入口拒收, 数据面不为编造参数兜底。

**判据(净化家族第八句)**: 参与比较/切片运算的参数值域校验必须在入口且
fail-loud——这两种运算对错值都不抛异常; 警惕"坏参数→空结果"路径(空结果
在展示层=合法空态, 假绿比报错危险)。

**回归**: test_trace.py +1(limit 0/-2 零名额、None 不限)、
test_trace_command.py +1(三种非法 since exit 2+合法照常), pytest **343 全绿**;
ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加第八形态(参数值域静默故障)。

## §59 第四十一轮: 前端键盘/无障碍/空态面(真实浏览器逐屏实测)

**选题**: 前端键盘可达性/空态从未专项(§18 只测过浮层 Esc, §22 只测过空态文案)。
真实 serve(token 态)+ 浏览器逐屏: '/' 聚焦、Tab 序、Enter/空格重放、Esc 关层
焦点归还、←→ 步进、零命中榜键盘追因、三形态空态(过滤无匹配/下钻无记录/
KPI 零值)。

**通过面**: '/' 聚焦过滤框✓; feed 条目 Enter 弹回放浮层✓; Esc 关闭后焦点
归还最后播放条目(aria-label 断言)✓; 浮层开着 → 步进换 trace(rpLastTid 变化)✓;
零命中榜行 Enter 追因(fq+fState.f+计数三处联动)✓; 空态文案区分"没匹配"与
"没有记录"且 fcnt=0/15、fpage 隐藏✓; focus-visible 样式在位✓。

**D-50 联邦矩阵下钻行仅鼠标可操作(实锤+修复, 中)**: Tab 遍历 6 跳全落榜行/
按钮, 矩阵行不在序列; `tr.focus()` 后 activeElement=BODY——`loadMatrix` 后加的
`tr.onclick` 漏了 tabindex/role/键盘三件套(同页其余行级交互全做对)。修复:
模板补 `tabindex=0 role=button aria-label`, 绑定共用 go() + onkeydown(M-1 同款
target 守卫), :focus-visible 名单加 `.matrix-link`(负 offset)。真实复验:
Tab 入行 Enter → `view=single&caller=agent-kb`✓。

**走查方法论(过程自纠, 值得记)**: 修复后浏览器复验仍旧值(withTabindex:0),
才 grep 发现 serve 启动时一次性读入 index_html(serve.py L453)——**改静态资源前
应先核实服务侧加载路径**(启动读一次 vs 每请求读盘), 别拿"改文件即可见"的
默认假设代替读码; 重启端口后复验才有效。与净化家族"动手前确认机制真实
执行路径"同源。

**回归**: test_stats_serve.py +1(静态守护: 可点行模板必含 tabindex、矩阵绑定
段必含 onkeydown), pytest **345 全绿**; ruff F,E9 通过。

**沉淀**: 无既有条目命中(kb search 前端域全查), 新建 `kb-20261023-77e1`
(自定义可点元素键盘三件套, 自审 accepted/verified)。

## §60 第四十二轮: stats 聚合计算面——limit 家族第四处与错误归位

**选题**: §58 判下"参与比较/切片运算的参数值域必须入口 fail-loud"后, 全仓
`[:limit]` 表达式 hunt 收敛到最后一处用户可控入口: `/api/feed?limit=`
(serve.py L401 `int(q.get("limit", 50))`)。stats 其余面(除零守卫、offset
感知、消化方向、AND 语义)已有 §29/§35/§37 测试网覆盖。

**D-51 feed_events limit 负数切片翻转(实锤+修复, 中)**: 探针 4 条事件
`limit=-2` 直调与 HTTP 双面均返回 `[t4, t3]`——"要最少给最多"(§51→§56→§58
→本轮, limit 家族第四处)。修复: `feed_events` ≤0 零名额, 与 read_traces
同契约。

**D-52 /api/feed?limit=abc 客户端错误伪装 500(实锤+修复, 中)**: `int()` 在
路由 try 内抛 ValueError → 兜底 except 回 500 `internal: ValueError`——4xx
的输入问题穿 5xx 的衣, 面板显示"internal:"误导为服务端故障。修复: 与
since/until 同位置入口校验, 非整数回 400 指明参数名与收到值。

**判据(第八句推论)**: 值域校验"入口拒收 + 被调方归一"成对——入口管**错误
归位**(兜底 except 分不清"数据坏 500"与"参数错 400"), 被调方管直调面兜底;
limit 表达式在四个模块独立重现, 佐证新入口会不断重新引入同类洞。

**回归**: test_stats_serve.py +2(feed_events limit 契约、serve 非整数 400),
pytest **347 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"limit 家族第四处 + 客户端错误伪装
500"新发现段(第三种故障形态: 有报错但状态码撒谎)。

## §61 第四十三轮: limit 家族收口——search() 公共 API 第五处

**选题**: §60 断言"limit 表达式在四个模块独立出现"后不服, 用 `[:limit]` 表达式
文本全仓穷尽 hunt(而非记忆中的模块清单), 命中 index/search 双查的后者:
`search.search()` 公共库 API 的 `rows[:limit]`。index 构建面本体(_records
排序由 iter_entry_paths 的 sorted 保证、id 重复 lint 点名、export 入口按主键
防撞 §54)防御已全, 无新坑。

**D-53 search.search limit 负数尾截翻转(实锤+修复, 中)**: 探针 5 条记录
`limit=-2` 返回 3 条(全量减 2)。这是全族**唯一裸入口**——其余四处都有工具面
(CLI/MCP/HTTP)间接触发过 limit 测试, search() 的 limit 只被正数测过。修复:
≤0 零名额, 与 sources/layers/trace/feed 同契约, 全族五处收口。

**判据(hunt 方法论升级)**: "修了 N 处同族"是漏第 N+1 处的认知陷阱——每轮
修复后以**表达式文本**做全仓穷尽(表达式是有限集, 记忆不是), 别按"我记得改
过哪些模块"圈范围。

**回归**: test_search_eval.py +1(limit 0/-2 零名额、2 照常), pytest **348
全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"limit 家族收口"新发现段。

## §62 第四十四轮: gate review/promote/set-scope 状态流面

**选题**: gate 公开写函数的枚举入参守门情况。CLI 面 `kb review --confidence`
有 argparse choices 挡着, 但 MCP `kb_review` 与直调 gate.review() 没有任何
校验——这是 §56(severity 非法值落盘)判据指向的同类面。

**D-54 review() confidence 非法值静默忽略(实锤+修复, 中)**: 探针传
`confidence="verifed"`(拼错)与 `"urgent"`(越界), 两处均**动作成功回执 +
status 照常流转 accepted + 写 verification 留痕**, 但 confidence 保持原值
(probable)——索引与回执口径不一致, 且比 §56 severity 更隐蔽: 垃圾值不落盘,
合法值原地不动, 连事后从数据里发现异常的线索都没有。修复: gate.review()
头部按 taxonomy `enums.confidence` 校验, 非法值 `GateViolation` 并列出合法
枚举; 探针复验两场景均拒, 拒绝时不留半成品(status/verification 均未动)。

**判据(§56 第二次独立命中)**: 同一判据(severity→confidence)在两个不同函数
上命中, 说明逐个hunt枚举参数是被动打法——应固化为**清单式普查**: 把 gate 全部
公开写函数(review/export_entry/set_scope/promote 等)的枚举入参列成清单, 统一
过一遍 taxonomy 校验, 一次收口而不是每轮撞一个。

**回归**: test_gate_write.py +1(非法值拒绝且不留半成品、合法值 verified 照常
提升), pytest **349 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§56 判据第二次命中"新发现段。

## §63 第四十五轮: lint/entry 失踪点名面

**选题**: lint.py 全规则 vs test_lint.py 覆盖对账——规则本体覆盖很全(schema/
duplicate id/引用/H1 围栏/占位段/指纹/stray 都有锚点), 把靶心移到**规则本身的
判据**上: §42 反失踪检查 `stray_entry_paths` 的判据是"kb 根散文件且可解析出
id"。

**D-55 语法坏的 kb 根散文件完全静默失踪(实锤+修复, 中)**: 探针三样本对置——
完好散文件被点名✓、无 front-matter 纯笔记不报(设计内)✓、**front-matter YAML
语法坏的散文件零输出**✗。它同时滑了位置与语法(有 id 行却未闭合流), 是"显然想
写条目"的两证齐全样本, 却比只滑位置的失踪得更彻底: 不进 index、stray 解析不出
id 不点名、lint 的 YAML 语法错误消息只覆盖 iter_entry_paths 内条目也够不着。
修复: stray 判据放宽为"带 id **或** yaml_error"(parse 层降级信息直接复用),
lint 消息按实际分叉措辞; 探针复验语法坏散文件被点名、纯笔记仍不报。

**判据**: **"点名条件建立在可解析性上"的失踪检测, 对坏得最彻底的样本天然
失明**——越该报警的样本越解析不出报警所需字段, 形成"完好者被点名、残骸者隐身"
的倒挂。与 §53"修复让问题隐身须显式点名"同一元规则: 每加一层降级, 就要为降级
样本单独建一条点名通道。

**回归**: test_lint.py +1(语法坏散文件点名+纯笔记不误伤), pytest **350 全绿**;
ruff F,E9 通过。

**沉淀**: 命中 §42 族主条目 `kb-20261022-8b8f` 追加"§63 坏得越彻底越隐身"新
发现段。

## §64 第四十六轮: stats 榜单三函数 limit 契约(§58 同族第六~八处)

**选题**: §61 判据"表达式文本穷尽"的机械执行——对 src/ 全仓重跑 `[:limit]`
grep 逐条对账。§43 说"五处收口"时, 同文件 stats.py 里躺着**三处裸 `[:limit]`**
(top_queries/top_consumed/zero_hit_board)没人看一眼——§60 修 feed_events 时
整个文件都在屏幕上, 视线只落在被报障的函数上。

**D-56 三榜单 limit 负数尾截翻转(实锤+修复, 中)**: 探针 `limit=-2` 下
top_queries/top_consumed 返回"全量减 2", zero_hit_board 因样本 2 条被"去尾
2"全吃掉。修复: 三函数统一 `rows[:limit] if limit > 0 else []`, 与全族契约
对齐; `summary(limit)`(内部固定 120)与 `_suggest`(纯内部)语义是"截断长度"
非"取前 N 名额", 无注入面不过度修。

**判据(§61 再收紧一档)**: **"修完并宣布收口"这个动作会提前关闭你的搜索**——
收口宣言写下的瞬间该家族在心里"处理完了", 而表达式实例数不因宣言减少。穷尽
必须是每轮的机械动作(grep→逐条对照守门代码→对不上立靶), 不是收口时的一次性
动作。本轮三处正是机械重跑撞出来的。

**回归**: test_stats_serve.py +1(三榜单 0/-2 零名额、2 照常), pytest **351
全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§64 收口宣言自己成了陷阱"新发现段。

## §65 第四十七轮: trace 文件 meta 行不可信输入面

**选题**: §26 净化家族(_coerce)的**覆盖范围**对账——净化器建在事件行上, 同
一文件的 meta 首行走另一条原始解析路径(`meta.get` / `int(meta["schema"])`),
从未被问过"你可信吗"。

**D-57 脏 meta 行打崩整库读取(实锤+修复, 高)**: 探针三场景——`schema:"2"`
(字符串数字)碰巧能过; **`schema:"v2"` → int() ValueError 崩 `read_traces`,
stats/feed/callers 三端点全挂**; meta 行是 JSON 数组 → `.get` AttributeError
同崩。爆炸半径与被净化保护的事件行崩掉完全相同, 而 trace 文件明示"由各客户端/
手工写入"属不可信输入。修复: 非对象 meta 行按缺 meta 跳过, 非数值 schema 按
本地版本兼容读取+warn(读不懂版本标记≠数据坏), 事件不丢; 探针复验三场景全存活。

**判据**: **净化以"输入边界"为范围单位, 不以"字段多少"为单位**——"净化器只
覆盖它被编写时盯着的那部分输入", 元数据行被潜意识归为"自家写侧可信"是灯下黑。
审净化器要问"这个边界内还有哪些解析路径没经过它", 不是"这个函数字段防全没"。

**回归**: test_trace.py +2(非数值 schema 兼容读取不丢事件 / 非对象 meta 行
跳过), pytest **353 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§65 净化家族灯下黑"新发现段。

## §66 第四十八轮: spider_export 同函数相邻两行防线不等厚

**选题**: §62"清单式普查"判据向函数内收缩——同一份数据在一个函数里被消费
多次时, 每次消费的防线是否等厚。读 `spider_export.to_record` 时发现 read_ids
与 consumed 两个相邻集合推导消费同一 `get_evs`, 守卫厚度却不同。

**D-58 consumed 裸取 `g["id"]` KeyError 掐断回放(实锤+修复, 中)**: read_ids
有 `isinstance(g.get("id"), str)` 守卫, 两行外的 consumed 是裸 `g["id"]`——
§52 净化删过 id 键的 get 事件, 只要 returned 里混进 null 元素(JSON 合法,
`_coerce` 不清列表元素), `None in returned` 判真, `g["id"]` KeyError 沿
to_record 上炸 /api/replay、/api/spider 500。探针场景 A 实锤 KeyError, 场景 B
(returned 无 null)对照通过; 修复补同款守卫后两场景均存活, consumed 干净为空。

**判据**: **"同函数第二行"**——防线是**表达式级**的不是**数据级**的, 同一变量
在本函数内第二次被消费时完全可以裸奔, 且相邻两行在评审视线里容易被归为"刚防
过的同一段逻辑"。修完某行对 X 的守卫后, 立即 grep X 在本文件的全部其他消费点
逐点确认; 评审时"上一行 `.get(k)` 下一行 `[k]`"相邻对直接按缺陷读。这是 §62
(清单式普查)与 §64(修完即失明)判据的微观终态: 视线单元可缩到函数内相邻两行。

**回归**: test_spider_export.py +1(get 缺 id 键 + returned 含 null 不崩),
pytest **354 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§66 同函数相邻两行防线不等厚"新发现段。

## §67 第四十九轮: cli trace export --latest 对净化可删键裸索引

**选题**: §66"同函数第二行"判据换尺度重跑——净化器(_coerce §52)声明 trace_id
非字符串**删键**, 即对全仓下游宣布"该键可能缺失"; 按新机械动作对全仓
`["trace_id"]` 裸索引 grep, 唯一命中 `cli.py` export --latest 的
`newest[0]["trace_id"]`。

**D-59 export --latest KeyError traceback(实锤+修复, 中)**: 探针写入最新事件
trace_id=12345(int)——`_coerce` 删键后 `newest[0]["trace_id"]` KeyError 未捕获,
CLI 直接 traceback。讽刺点是 `_newest_first` 把坏样本排最前, "取最新"必踩雷;
同一数据 `trace list` 正常(全用 `.get`)。修复: 取键校验非字符串则如实报错
退 1 引导显式 `<id>`(不做"跳过坏条找次新"的过度设计); 探针复验 rc=1 干净报错。

**判据**: **净化器的"删键"是对全仓下游的契约变更**, 消费点散布在其他模块,
写净化器的人看不到。每新增删键分支即对该键名全仓裸索引 grep 一遍; 评审看到
`ev["k"]` 先问"k 是不是净化可删键"。§66+§67 合并: 防线审计的视线单元从
"相邻两行"扩到"生产者-消费者全链"。

**回归**: test_trace_command.py +1(坏 trace_id 最新事件下 export --latest 退 1
不 traceback), pytest **354 全绿 + 1 flaky**(test_spider_live 时序用例全量套件
下偶发失败、单跑 10/10 通过, sleep 0.3/max_sec 2.5 真实等待在负载下不足,
登记观察非本轮引入); ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§67 净化删键契约没有下游消费清单"新发现段。

## §68 第五十轮: 净化可删键全链普查——生产者往消费集合塞 None

**选题**: §67 机械动作整轮执行——对 _coerce 全部净化可删键(trace_id/id/
caller_repo/layer/source/ts/layers/ext/suggest/read/query)做全仓裸索引普查,
消费点逐条核对来源面, 顺路审到消费集合的生产者。

**D-60 _gets_by_trace 把 None 装进消费集合(实锤+修复, 中)**: get 事件 id 被
净化删键后, `add(g.get("id"))` 不看类型, None 进入"已消费 id 集合"。三下游
三症状: **top_consumed** `g["id"] in consumed` 真分支裸取 KeyError; **feed
read** None+str 混合 `sorted()` TypeError(单 None 时输出 `[null]` 污染 API);
**aggregate consumed_total** 把 None 记成真实消费——KPI 虚高不崩但说谎, 比崩
更隐蔽。探针三场景实锤(场景1 TypeError/场景2 KeyError/场景3 虚报 1), 修复在
生产者侧一行 `isinstance(gid, str)` 类型收敛, 复验三场景全干净、consumed_total
归正。

**判据**: §67 的另一半——删键的下游债不只有裸索引点, 还有**把可缺值装进有
类型语义容器的生产者**。审删键分支问两句: "谁裸索引这个键"(§67)、"谁把它装进
容器再分发"(§68)。装容器处=类型收敛点, 守一次胜过消费方逐点补防。

**回归**: test_stats_serve.py +1(删键 get 混正常 get: top_consumed 只计正常、
read 不 TypeError、consumed_total 不虚报), pytest **356 全绿**(flaky 用例本轮
未复现); ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§68 生产者往消费集合塞 None"新发现段。

## §69 第五十二轮: stat --format md 多行 title 劈碎表格

**选题**: §65"净化覆盖范围"判据换面重跑——转义函数是净化器的孪生面。审
cli.py 全部输出格式化点, `_md_cell`(stat --needs-scope --format md)只转义竖线。

**D-61 多行 title 劈碎 md 表格(实锤+修复, 低)**: title 是 YAML 多行块(lint
不禁止多行标题)时, 旧 `_md_cell` 把换行原样打进单元格——1 条记录输出 3 行
(半行+游离行+残尾), 表格碎裂, 按行解析下游全错位。探针实锤后修复: 先折叠
全部空白为单空格再转义竖线(与 entry.summary 同款), 复验一记录一行、行尾闭合。

**判据**: **一切"把自由文本放进结构化载体"的函数都是净化器**——先写出目标
载体的完整不变量(md 单元格=单行+无裸竖线), 逐条对照处理是否齐全, 不是"想到
哪个字符转哪个"。§65 判据第三次独立命中(事件行→meta 行→转义器)。

**回归**: test_cli.py +1(多行+竖线 title: 数据行 1 条、行尾闭合、折叠+转义
断言), pytest **357 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§69 转义器也是净化器"新发现段。

## §70 第五十三轮: export_entry source 回填相邻两行各种半个防法

**选题**: §66"同函数第二行"判据重跑, 从 spider_export/cli 换到 gate.export_entry
——front-matter 是不可信输入, 回填 source.project 时对 `fm["source"]` 的相邻
两行消费值得逐行对账。

**D-62 source 非对象崩 export(实锤+修复, 中)**: 上行 `{**(fm.get("source") or {})}`
`or {}` 防 None 漏标量(`source: manual` → `{**"manual"}` TypeError); 下行
`fm.get("source", {}).get("project")` 中招 §47 陷阱(`source:` 空值 → 默认值不
生效 → `None.get` AttributeError)。探针双场景实锤(搬移进行到一半崩, 破坏性
流程尤其危险)。修复: `isinstance(dict)` 类型收敛一次+非对象 warn, 两行共享
同一事实; 复验两场景搬移照常、source.project 为干净字符串。

**判据**: §66 的对称子形态——**两侧都有防、防法还不同**。"一处防一处裸"评审
显眼, "两个惯用式各防一半"双双过审。识别信号: 同一变量相邻几行防御写法不一致
(`or {}` vs `.get(k,{})` vs isinstance)时逐式问"你防不住什么"再取并集。

**回归**: test_gate_write.py +1(source 空值/标量两形态 export 照常、project
回填为字符串), pytest **358 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§70 相邻两行各种半个惯用防法"新发现段。

## §71 第五十四轮: INDEX.md 多行 title 劈碎一记录一行契约

**选题**: §69 判据的操作化重跑——对自由字段 title 列出全部输出载体清单
(stat md 单元格=已修 / INDEX.md 列表行 / index.jsonl=JSON 转义天然安全), 逐
载体核不变量。第二站 `index._md` 命中。

**D-63 INDEX.md 多行 title 劈行(实锤+修复, 低)**: title 是 YAML 多行块时
`_md` 原样插入列表行, 2 条记录输出 3 行(1 游离行), "一记录一行"契约碎裂,
按行消费的 L2 面错位。同函数内 summary 已折叠(title 裸奔)——§66"第二行"在
字段维度重现。修复同款 `re.sub(r"\s+", " ")` 折叠, 复验 2 记录 2 行无游离。

**判据**: 修一个载体≠修该字段——**每个自由字段列全部输出载体清单逐载体核**。
jsonl 因 JSON 转义免检, md 面两载体一防一裸。§69 判据当轮即复用见效, 证明
其可作为机械动作固化。

**回归**: test_index.py +1(多行 title 两记录恰两行、折叠断言), pytest
**359 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§71 同一字段第二载体裸奔"新发现段。

## §72 第五十五轮: autostart 计划任务 PowerShell 单引号裸插值(命令注入)

**选题**: §69/§71"自由文本进结构化载体"判据按**爆炸半径排序**优先扫最重档——
shell 命令拼接。`autostart.install_windows` 把 repo 路径与 default_caller
裸插进 `-Execute '{cmd}' -Argument '{args}'` 单引号串, 零转义。

**D-64 install_windows 断串/命令注入(实锤+修复, 高)**: 探针替换 `_ps` 捕获
脚本——路径 `O'Brien` 单引号原样入串(注册 cmdlet 必炸且报错指向假因),
`--default-caller "evil'; <命令>; '"` 断串后可在本机用户上下文执行任意命令。
修复 `_psq()` 按 PS 规则单引号加倍, 三个插值点全过; 权威复验用**真实
PowerShell 解析器**回吐变量值: 注入串完整保留为字面量、`7*7` 未执行。
探针期间自查一桩: 自写的 regex 判据(`'; ` 即泄漏)对加倍转义假阳性(`'';`
第二个 `'` 非闭合符), 真解析器才可信。

**判据**: 载体清单按爆炸半径排序, shell 拼接(RCE 原语)>md 错位;**验证转义
用目标载体真解析器, 不要另发明近似判据**。

**回归**: test_autostart.py +1(路径/caller 单引号加倍、引号成对), pytest
**360 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§72 shell 载体漏转义=执行"新发现段。

## §73 第五十六轮: systemd unit 值内换行注入指令行

**选题**: §72 载体清单判据在 autostart 模块内走完第二站——同一 serve 命令的
Linux 载体 `render_systemd_unit`。逐条目答两问: 破坏字符=换行(unit 值跨行即
新指令行), 转义语法=**无**(systemd 引号不跨行、无值内换行转义)。

**D-65 systemd unit 换行注入(实锤+修复, 高)**: 探针把
`--default-caller "evil\nExecStartPre=/bin/sh -c pwned"` 喂进渲染, 实锤
`ExecStartPre=` 作为独立指令行落盘(下一次服务启动即执行)。修复: 渲染入口
对 command/args/working_dir 三字段拒收换行(fail-loud ValueError), cli 侧把
ValueError 并入 autostart 友好报错通道(旧 except 元组接不住会 traceback)。
Windows 面复核无需二次修: PS 单引号串允许值内换行, 不破坏安全。

**判据**: 载体条目两问——"破坏字符是什么"+"该载体有没有转义语法"。**转义表
为空的载体(INI 族/CSV 裸字段/日志行)唯一防线是准入拒收**, 守门点选在生产者
出口。与 §72(有转义语法的 shell→正确转义)合成完整决策树。

**回归**: test_autostart.py +1(含换行 caller 渲染拒绝), pytest **361 全绿**;
ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§73 转义不存在的载体只能拒收"新发现段。

## §74 第五十七轮: _is_uv_venv 全文子串误判(§53 判据的格式面变体)

**选题**: 换靶 bootstrap.py(§45 只防过 doctor 崩溃面, init/安装命令生成分支
未细审)。审 `_is_uv_venv` 时对照 docstring 承诺与实现, 发现"写明 `uv = <ver>`
行, 实现是全文 in"。

**D-66 uv venv 误判给标准用户开死路命令(实锤+修复, 低)**: 标准 venv 的
`command = /home/uvuser/... -m venv` 行含 "uv" 子串(用户名/路径恰好命中)即误
判, doctor 给标准 venv 用户开出机器上不存在的 `uv pip install` 命令(探针场景
A 误判 True)。修复: 行级键匹配(`uv =`/`uv=` 行首锚定), 复验误判场景 False、
真 uv venv 仍 True、装包命令回到 `python -m pip`。

**判据**: **识别 key=value 格式文件(pyvenv.cfg/ini/env)的标志必须行级键匹
配**——格式文件的"检测"就是廉价解析器, 写它就得按解析器规矩来; 全文 in 对
"路径/用户名碰巧含标志词"恒误判。§53 判据(子串恒真)从值面打到格式面的第二
个方向。附"承诺审计": docstring 带格式示例的判据函数, 测试照示例造正反例。

**回归**: test_bootstrap.py +1(uvuser 用户名标准 venv 不误判), pytest
**362 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§74 格式文件检测=廉价解析器"新发现段。

## §75 第五十八轮: _dispatch get 分支裸取净化可删键(§66 判据收缩到同函数两分支)

**选题**: 审 serve 全端点/launcher/userconf/stats 均无果后转 spider_live, 对照
`_dispatch` 两分支对同一 trace 事件的字段取法, 发现 search 分支经
event_to_updates 有 `isinstance(m.get("id"), str)` 守卫而 get 分支裸取
`ev["id"]`。

**D-67 get 分支 KeyError 静默丢播(实锤+修复, 低-中)**: trace 文件经 §52 净化
把非字符串 id 删键后, get 分支 `ev["id"]` 直接 KeyError, 被 run 循环
`except Exception: continue` 吞掉——该条"已读消费"标注在直播流静默丢失(探针
场景A id=12345 修复前 KeyError, 修复后安全跳过; 场景B 合法 id 照常发 you
标注)。修复: `if ev.get("ok") and isinstance(ev.get("id"), str)` 对齐 search
分支口径。

**判据**: **净化器删过的每个键, 全部消费点按同一口径处理**——拿净化删键清单
(trace_id/id/caller_repo/layer/source/ts)当检查表 grep 裸索引, 同函数内"一处
守卫一处裸取"即缺陷。异常被上层循环吞掉时这类炸点是**静默丢数据**而非崩溃,
比崩溃更难发现。§66"两行等厚"判据收缩到同一函数内部的两分支。

**回归**: test_spider_live.py +1(_coerce 删键后 _dispatch 不崩不发/合法 id 照常
发), pytest **363 全绿**; ruff F,E9 通过。观察: 首跑 test_ingest_append_dedup_and_redlines
偶发 ConnectionResetError(WinError 10054), 单跑与复跑均过——serve 测试第二例
flaky(前有 test_spider_live 时序用例), 登记暂不修。

**沉淀**: 命中 `kb-20261023-463c` 追加"§75 同函数两分支对净化可删键同口径"新
发现段。

## §76 第五十九轮: serve do_POST 出错路径不 drain 请求体→401 被 RST 吞(登记 flaky 转正)

**选题**: 上一轮把"test_ingest 偶发 ConnectionResetError"从"环境 flaky 暂不修"
提级为走查对象。循环探针首轮实测复现率 1/8(单跑/16 连跑单文件全过——证实它
只在套件负载下拉长两段时间差时出现)。

**D-68 出错路径不 drain 请求体, 已写出的 401 被 RST 吞(实锤+修复, 中)**:
`http.client` 发带体请求是"头段+体段"两次 write; 旧 `do_POST` 鉴权失败直接回
401 并 close、全程不读 body——体段晚于 close 到达时内核回 RST, 把客户端尚未
读走的 401 字节一并丢弃(WinError 10054/10053)。探针用原始 socket 受控时序
(发头→睡 0.4s→发体)让必现化: 修复前读响应必炸, 修复后稳定读到
`HTTP/1.0 401`。修复: Content-Length 解析+回读提到全部错误返回之前(404/401/400
统一先 drain), 超 64KB 不读直接关(防放大)。

**判据**: **带体请求的任何错误响应, 回之前先把请求体读干**(RFC 9110 §10.1.4)
——"先校验后读体"的裸 HTTP 服务端都中招; 这类缺陷的现场特征是**偶发连接重置
而非稳定失败**, 极易被误登记为"环境 flaky 暂不修"。方法论: 被登记的 flaky 是
走查的免费选题清单——"只在负载下出现"本身就是机制线索(负载拉开了哪两件事的
时间差?)。验证方法: git stash 回退源码确认新测试对旧代码敏感(否则测试是摆设)。

**回归**: test_stats_serve.py +1(受控时序: 迟到 body 后 401 必须可读; stash 回退
即失败), pytest **364 全绿**; ruff F,E9 通过; test_stats_serve.py 连跑 8 次
0 失败(修复前 1/8)。

**沉淀**: 新建 `kb-20261023-1dd3`(backend, 独立病灶族不入 463c), 自审
accepted/verified(evidence=受控探针+8 连跑)。

## §77 第六十轮: _coerce 列表归一不做元素级——layers:["x"] 打崩 stats 四聚合

**选题**: 按 §75 判据全仓 grep 净化可删键裸索引消费点(存量均有守卫, 无新靶)
后, 转审 `_coerce` 净化面自身: §50 把 layers/ext 归一为 list 的循环只校验
"是不是 list", 列表**元素**与 layers 元素内的 matched 完全裸奔, 而 stats 全部
消费方假定"层是 dict、matched 是 list"。

**D-69 结构字段元素级裸奔(实锤+修复, 中)**: 手工/异构客户端 trace 文件写
`layers: ["坏层", {...}]`, 通过既有归一进缓存后, `by_source`/`callers`/
`feed_events`/`top_consumed` 四函数全部 `ly.get(...)` AttributeError(探针实锤
四连崩; serve stats/callers/feed 端点在同一文件下 500)。修复: `_coerce` 增加
元素级净化——layers/ext 剔除非 dict 元素(换引用), matched 须为 list 否则删键、
其内非 dict 元素 `m[:] =` 就地过滤(缓存共享 dict 引用不可换), 全部带 warn。

**判据**: **净化深度 = 消费方下钻深度**——"解析期一次归零"原则下, 消费方对
结构的每一层假设(层是 dict → matched 是 list → 元素是 dict)都要在净化层有
对应校验, 否则只是把炸点从第一层推到第二层。审计法: 拿消费方下钻链
`s.get("layers") → ly.get("matched") → m.get("id")` 当深度尺量净化器。

**回归**: test_trace.py +1(元素级剔除+标量 matched 删键+缓存幂等), pytest
**365 全绿**; ruff F,E9 通过。

**沉淀**: 命中 `kb-20261023-463c` 追加"§76/§77 flaky 免费选题+净化深度下钻"
合并新发现段(两判据同根: 审计既有防线的边界在哪停住)。

## 走查方法论教训(§18 自我纠错, 保留原样)

曾误报"Esc/✕ 关不掉浮层"——`#rp` 元素常驻 DOM, 关闭仅移除
`.open` 类, 断言误用 `!!querySelector('#rp')`(元素存在性)所致; 修正为 `.classList.contains('open')` 后
重测全部通过。systematic-debugging 的"先根因后结论"在此拦下了一轮假修复。browseruse evaluate 返回值
需取 `content[0].text`, 手写 IIFE 会被二次包装吃掉返回值(用纯表达式)。

