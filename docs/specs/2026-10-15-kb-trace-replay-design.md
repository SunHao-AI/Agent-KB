# KB Trace 采集与可视化回放 设计

- 日期: 2026-10-15
- 状态: 已评审通过 (2026-10-15, 分节评审: 数据层与开关 / 插件式架构 / 回放画面 / 转换器路线 / 测试验收)
- 上游: `docs/specs/2026-10-12-agent-kb-design.md` (P0), `docs/specs/2026-10-13-agent-kb-p1-design.md` (P1)
- 参考: [prompt-spider-ui](https://github.com/Kirito14IT/prompt-spider-ui) (MIT, 回放格式 `prompt-spider-session/v1`)

---

## 1. 背景与目标

现状: `kb search` / MCP `kb_search` 执行后**不留任何痕迹**。Agent 命中了哪些索引条目、是
怎么命中的(命中哪个字段、哪个过滤条件淘汰了什么)、返回后 Agent 是否真的读了全文 — 全部
不可见。知识库运营缺数据: 哪些 query 零命中、哪些条目从未被消费, 无从谈起。

目标: 让"Agent 如何命中知识库"可回放、可观看。参考 prompt-spider-ui 的动画形态, 但
**数据先行、渲染可插拔**: 采集层独立开关, 数据层是纯 append-only JSONL, 消费层
(CLI / 转换器 / 未来的自建 web 页)互不依赖。

## 2. 范围

**In scope**
- Phase 1: `trace.py` 埋点(可选开关) + 集中落盘 JSONL + `kb trace list/show` CLI
- Phase 2: `kb trace export --format spider` 转换器, 产物导入 prompt-spider-ui 观看
- MCP `kb_search` / `kb_get` 与 CLI `kb search` 双入口埋点(CLI 加 `--trace` / `--no-trace`)

**Out of scope (挂账, 见 §9)**
- 自建 `kb web` SVG 回放页(数据模型已预留, 用转换器不满足需求时再补)
- 实时直播(Canvas/轮询)、统计报表、鉴权、RAG 相关

## 3. 总体架构

```
┌─ 采集层(开关控制) ─┐   ┌─ 数据层(事实源) ───┐   ┌─ 消费层(可插拔 readers) ─┐
│ search/get 埋点    │ → │ traces/*.jsonl     │ → │ kb trace list/show      │
│ 默认关闭, 零成本    │   │ append-only, gitign│   │ spider 转换器(Phase 2)   │
└───────────────────┘   └────────────────────┘   │ 未来: kb web (SVG 回放)  │
                                                 └─────────────────────────┘
```

**唯一耦合点是 JSONL 文件格式(schema 版本化)。** 采集层未开启时对检索零影响; 新增消费端
不改采集与数据。三层各自可独立单测。

代码落位:

```
src/kb/trace.py        # 开关判定 + schema 常量 + append 写入 + reader(list/show 用)
src/kb/spider_export.py # Phase 2: trace → prompt-spider-session/v1 纯函数转换
src/kb/cli.py          # 新增 `kb trace` 子命令组; search 加 --trace
```

## 4. 采集层 (`src/kb/trace.py`)

### 4.1 开关判定(默认关闭)

优先级从高到低: CLI `--trace`(显式开) > `--no-trace`(显式关) > 环境变量
`KB_TRACE=1/0` > 仓根存在标记文件 `.kb-trace` > **默认关闭**。MCP 场景用环境变量或标记
文件(`kb.mcp` 启动参数 `--trace` 等价于置位)。关闭路径 = 一次布尔判断即返回。

### 4.2 落盘位置与写入

- 位置: Agent-KB 仓根 `traces/YYYY-MM-DD.jsonl`(按天分文件)。仓根定位:
  `Path(kb.__file__).resolve().parents[2]`(kb 包随 Agent-KB 仓发布, submodule 挂载点
  即仓根), 业务仓内调用无需配置。
- 文件首行(每个新文件一次): `{"kind":"meta","schema":1}`。
- **红线: trace 只含元数据+摘要, 绝不含知识正文**(与收录红线"敏感内容不进日志"一致)。
- 写入失败静默吞掉(权限/磁盘/并发均可), 检索永不因埋点报错。并发按"行级 append +
  失败放弃"处理, 不加锁(P2 若观察到交错坏行再升级)。

### 4.3 埋点位置

`layers.search_layers()` 是唯一双层入口, CLI 与 MCP 均经它 — 在其外层加 traced 包装,
一处生效两处。`get_layered()` 同样包装一条轻量 get 事件。`search()` 内部改造: 评估每条
记录时记住"死因"(死于过滤器 / 死于关键词 / 命中及命中字段), 对外返回值不变, 旧调用零影响。

### 4.4 trace 事件 schema (schema=1)

```json
{
  "kind": "search",
  "trace_id": "t-20261015-a1b2",
  "ts": "2026-10-15T14:32:05+08:00",
  "source": "cli | mcp",
  "caller_repo": "flysee_video_web",
  "query": "vite hmr",
  "filters": {"type": "pitfall", "domain": "frontend", "confidence": "verified",
               "tag": null, "scope": null, "status": null},
  "limit": 10,
  "duration_ms": 12,
  "layers": [
    {"repo": "docs", "scanned": 208,
     "rejected": {"filter": 150, "query": 40},
     "matched": [{"id": "kb-20261012-7f3a", "title": "...", "scope": "project",
                   "hit_fields": ["title", "tags"], "hit_spans": [[0, 4]], "rank": 1}],
     "taken": 3, "truncated_at_limit": false}
  ],
  "returned": ["kb-20261012-7f3a", "..."]
}
```

```json
{"kind": "get", "trace_id": "t-20261015-a1b2", "ts": "...", "source": "mcp",
 "caller_repo": "...", "id": "kb-20261012-7f3a", "layer": "docs", "ok": true}
```

- `caller_repo`: 由 `--repo` 路径推断(resolve 后目录名小写, 与 index repo 字段同口径)。
- `hit_fields` / `hit_spans`: 对 `title + tags + summary` 拼接文本做与现实现一致的
  小写子串匹配, 按字段边界反解命中的字段与偏移。
- get 事件的 `trace_id`: 同 caller_repo 最近一条 search 的 id(尽力关联, 关联不上为
  null)。用途是区分"被返回"与"真被消费", 不追求强一致。

## 5. CLI (`kb trace`)

- `kb trace list [--repo ...] [--caller X] [--since DATE] [--zero-hit] [--limit N]`
  — 表格: 时间 / source / caller / query / 命中数 / trace_id。零命中标记。
- `kb trace show <trace_id>` — 单条完整 JSON(含逐层死因与 matched 明细)。
- 数据目录不存在或为空: 打印引导(如何开启 KB_TRACE), 退出码 0。

## 6. Phase 2 — spider 转换器 (`src/kb/spider_export.py`)

产物为 prompt-spider-ui 回放格式 `prompt-spider-session/v1`(`initialConfig` + `config`
+ 事件快照 + 有序 `log`, `log` 项含递增 `revision` 与相对秒 `at`), 经其
`spider_import_session` 的 `record` 参数或浏览器导入观看。**不修改对方代码, 不依赖其
安装**(纯 Python 序列化; 观看侧需 Node 20+ 与克隆的 prompt-spider-ui)。

命令: `kb trace export <trace_id> --format spider -o out.json`

### 6.1 映射规则

| trace 语义 | spider 表达 |
| --- | --- |
| 会话 | 一条 trace = 一个会话, `unit:"word"`, `prompt`=query, title 含 caller/时间 |
| query 分词 | `tokenIndex` 逐词(中文按现有 `split()` 词序) |
| 命中条目 | 事件, `route` 三分支改名: `code`→"项目层命中", `model`→"通用层命中", `you`→"已读消费" |
| 被 kb_get 读过 | 同 id 二次更新 status→completed(导入后按 log 时间重放心跳) |
| hit_fields / spans | 事件 `detail` 文字(如 `hit: title+tags @ [0,4]`) |
| 双层扫描/淘汰计数 | subtitle + 事件 detail(`docs 扫描208 过滤-150 词-40`) |
| limit 截断 | subtitle 注记(`limit=10, 截断于通用层`) |

`log.at` 由 trace 内时间戳归一为单调相对秒(同 ts 事件按 schema 字段序加稳定小步长),
保证导入后回放顺序确定。**有损项**(渲染原语缺失, 接受): 扫描线动画、字段高亮、截断
弹回 — 均降级为文字元信息。

> **实现期修订(2026-10-15 终审)**: 转换器按 `unit:"task"`(每命中条目一事件)实现, 未做
> `unit:"word"` 分词与 `prompt`/`tokenIndex` 字段。record 已经 prompt-spider-ui 真机
> 校准通过(对端 `validateRecord` 校验 + 浏览器回放实测: 三分支计数、事件 inspect 显示
> hit 字段、中文分支筛选均正常); 校准点: `version/duration/status` 字段、log 项
> `type`(configure/events/complete)、events 批 1..100 分片、subtitle≤160 截断。

## 7. 错误处理汇总

| 场景 | 行为 |
| --- | --- |
| 埋点写盘失败 | 静默, 检索不受影响 |
| trace 文件缺 meta 行 / schema 版本高于当前 | reader 跳过并警告, 不崩 |
| JSONL 坏行(理论不该有) | reader 跳过该行并计数警告 |
| `kb trace show` 未知 id | 明确报错, 退出码 1 |
| 转换器遇到零命中 trace | 正常导出(会话内 0 事件 + subtitle 注明), 合法 |

## 8. 测试与验收

pytest(基线 118 → 预计 +15 左右), 全部走 tmp_path, 不碰真实 traces/:

1. 开关优先级四场景; 关闭时 search 行为与现版本逐字节一致(回归)。
2. schema: meta 行仅一次; 事件字段完整; **事件不含正文**断言。
3. 死因统计恒等式: `rejected.filter + rejected.query + len(matched) == scanned`。
4. hit_fields/hit_spans 与真实匹配一致(构造 title/tags/summary 各态样例)。
5. get 关联: 同 caller 最近 search 命中; 无关联时 null。
6. reader: 空目录/缺 meta/坏行/schema 不符四场景。
7. 转换器: fixture trace → record 结构断言(meta 行、revision 递增、at 单调、三分支
   改名、detail 内容); 零命中 trace 导出合法; 同一 trace 两次导出字节一致(确定性)。

端到端验收: 开启开关跑一次 MCP `kb_search` + `kb_get` → `kb trace show` 可见关联 →
`kb trace export` → 克隆的 prompt-spider-ui 导入 JSON → 动画回放可见词条、分流与已读
心跳。关闭开关后全仓回归测试全绿。

## 9. 显式挂账

| 项 | 触发条件 |
| --- | --- |
| ~~spider record 真机校准~~(已完成 2026-10-15: 对端校验器+浏览器回放实测通过, 见 §6 修订) | — |
| `unit:"word"` 逐词模式对齐(prompt/tokenIndex) | 需要蜘蛛逐词抓取的演示效果时 |
| 自建 `kb web` SVG 电影级回放页(扫描光束/爬虫精灵/发光蛛丝, 线框与分镜 P0–P4 已评审) | 转换器"导出→导入"仪式感不够用、或有损表达挡住深读时 |
| 实时直播(轮询 trace 自动跟进最新) | 自建 web 落地后二期评估 |
| 统计报表(命中率/热门条目/零命中 query 榜) | 积累 ≥2 周真实 trace 后 |
| 并发写坏行防护 | JSONL 出现实测交错坏行时 |

## 10. 决策记录

- **数据先行、渲染可插拔**: 用户明确要求插件式、可开关; 三层以 JSONL 为唯一耦合。
- **集中落盘到 Agent-KB 仓**: 跨仓检索 trace 单点汇聚, submodule 路径可自定位。
- **Phase 2 走 prompt-spider-ui 转换器而非自建前端**: 白嫖成熟动画与确定性回放引擎;
  语义有损项已列明并被接受; 自建 web 保留为挂账升级路径。
- **trace 不含正文**: 安全红线前置, 与知识库收录红线同构。
