# 长周期运行指标快照与消化回路 — 设计文档

> 日期: 2026-11-11 · 仓: Agent-KB · 方案: A(周指标快照落盘 + 消化工单)
> 目标: 支撑多业务仓真实流量的长时间观测——周节奏出指标趋势与消化建议,
> 月度试点期末可 diff 快照做深分析; 所有写库动作仍走既有门控, 不新开通道。

## 0. 背景与约束

- 流量来源: 已有业务仓在用(现证: `docs/reports/zero-hit-2026-11-09.md` 消化率 3%,
  caller 含 agent-kb 与 flysee-video-setting), 多仓真实流量。
- 产出形态(用户四项全选): 周期指标报告 / 面板趋势视图 / 期末深分析 / 消化回路半自动化。
- 节奏: 月度试点 + 周报。
- 红线沿用: Agent 沉淀只产 draft、可自审 accepted(evidence + confidence 提升)、
  永不改 scope、沉淀前 `kb search` 去重、追加新发现必须补中英 tags(#3b)。

## 1. 指标定义(零新计算)

全部复用 `src/kb/stats.py` 现成函数, 快照层只做**切窗 + 序列化**, 不新写任何口径:

| 指标块 | 来源函数 | 取用字段 |
| --- | --- | --- |
| 核心 KPI | `aggregate(searches, gets, since, until)` | hit_rate / consume_rate / searches / not_executed_count / returned_total / consumed_total / saved_chars_est / saved_unknown_count / overhead_chars / by_caller / by_day / cold_start |
| 延迟 | `latency()` | n / p50_ms / p95_ms / avg_ms / max_ms |
| 零命中榜 | `zero_hit_board(win, limit=30)` | board / digested / digest_rate |
| 多仓归因 | `callers_matrix()` | 各 caller 窗口内计数 + stale(>14d 掉线), 落盘为快照顶层 `callers` 键(区别于 `metrics.by_caller` 的逐日聚合) |

- 周号解析: 接受 `YYYY-Www`(如 `2026-W45`), 用 `date.fromisocalendar(y, w, 1/7)`
  得周一/周日; 非法值 argparse 即拒(对齐 `_date_arg` 入口即拒风格)。

- 窗口 = **上一自然周(周一~周日)**, 与面板 R6 自然周口径一致。
- 入参先过 `denoise()`(剔 pytest 合成语料)与 `effective()`(剔未真正执行的 search),
  与面板当前口径完全一致。
- 冷启动沿用 `cold_start`(样本 <7 天不出比率), 快照照录该标志。

## 2. 快照落盘(schema 与幂等)

- 路径: `traces/metrics/YYYY-Www.json`(如 `2026-W45.json`), 每周一个文件。
  - **子目录 + `.json` 单数后缀双保险**: trace 读取侧是 `glob("*.jsonl")`
    (trace.py `_iter_raw`), lock sidecar 用 `.lock` 后缀避开 glob 是既有先例;
    快照必须保证不被 `read_traces` 当 trace 事件解析。
  - 实施第一步先写"read_traces 不吞 `traces/metrics/`"回归测试, 固化该兼容点。
- 字段:

```json
{
  "schema": 1,
  "week": "2026-W45",
  "since": "2026-11-02", "until": "2026-11-08",
  "generated_at": "<ISO8601>",
  "metrics": { "…aggregate() 原样…": null },
  "latency": { "…latency() 原样…": null },
  "zero_hit": { "board": [], "digested": [], "digest_rate": 0.0 },
  "callers": { "…callers_matrix() 摘要: 各仓计数 + stale…": null },
  "warns": []
}
```

- **幂等**: 目标文件已存在 → 拒绝覆盖并退 1; 显式 `--force` 才重写。
  理由: 月度深分析 diff 四周快照, 历史数字必须可比; 重写会静默改变已归档曲线,
  只允许留 git diff 痕迹的显式操作。
- 随 traces 每日 18:30 定时任务一并提交 git(同目录树, 提交面零改动)。

## 3. 生成命令 `kb trace snapshot`

- 签名: `kb trace snapshot [--week YYYY-Www] [--force] [--format md|json]`,
  默认上一自然周; 挂在既有 `trace` 子命令树(与 `trace report` 并列, cli.py 现有分支旁)。
- 行为:
  1. 切窗(§1)→ 聚合 → 写快照文件(§2 幂等);
  2. stdout 输出周报 markdown: 本周 KPI + **环比**(读上一周快照文件 diff;
     上周快照缺失时只报绝对值并标注"无环比基期");
  3. **消化工单建议清单**: 对本期待消化零命中词逐个跑现库检索——
     - 命中近似条目 → 建议"补 tag(中英各一组, 红线 #3b)/改 summary", 给出目标条目 id;
     - 零命中 → 建议"立新条", 给出建议 type/domain 与查询原文。
  4. 归档沿用 `docs/reports/zero-hit-YYYY-Www.md` 命名(与既有周报同目录同风格)。
- **工单只出建议清单, 不自动写库**。落地动作(补 tag / 改 summary / kb new)
  由人审后走 `kb_update` / `kb_new` / MCP `kb_review` 既有门控, 红线不变。
  理由: 自动写库会把 3% 的消化率问题变成噪音灌库问题, 且违背门控红线设计。

## 4. 面板趋势视图

- 新端点 `GET /api/metrics`: 只读 `traces/metrics/*.json`, 按 week 排序返回数组;
  不在服务端现算(单一数据源=快照文件), 解析失败的单个文件跳过并计入 `warns`
  (防御思路沿用 `_coerce`: 不可信输入不炸面板)。
- 面板新增"周趋势"区: hit_rate / consume_rate / digest_rate 三条折线 +
  searches 柱; 快照 <2 个时显示"数据不足"占位(一条折线不成趋势)。
- 现有 R6 瞬时窗口(7d/30d 按钮)保留不动, 与周趋势互补: 瞬时看当下, 快照看历史。

## 5. 定时与失败兜底

- 每周一: 每日 18:30 定时任务顺带执行 `kb trace snapshot`(上周窗口已闭合);
  snapshot 失败**仅告警**, 不影响当日 traces 提交与任务整体成败。
- 任何时间可手动 `--week YYYY-Www` 回补历史周(traces 按日入 git, 重算可行);
  回补产物仍是新文件即新事实, 受 §2 幂等保护(已存在需 `--force`)。
- 读侧(§4 /api/metrics 与环比)对缺文件/坏文件全部降级为 warns, 不抛错。

## 6. 测试

- 切窗边界: 周一/周日边界日归属、跨年 ISO 周号(如 2026-W01 vs 2025-W53);
- 幂等: 已存在拒覆盖退 1, `--force` 重写生效;
- schema: 快照必备键齐全, metrics/latency 字段与 stats.py 返回逐键一致;
- **兼容回归(先写)**: `read_traces` 不解析 `traces/metrics/*.json`;
- 环比两分支: 有上周快照出 diff / 无上周快照只报绝对值;
- 工单启发式: 近似命中→补 tag 建议、零命中→立新条建议, 两分支各至少一例;
- `/api/metrics`: 空目录返回空数组、含坏文件返回 warns 不 500;
- 全部写操作用 tmp_path(pytest 合成 caller 剔噪机制已验证不污染真实 traces)。

## 7. 改动面预估

| 文件 | 改动 |
| --- | --- |
| `src/kb/metrics.py` | **新增**(约百余行): 切周、聚合编排、序列化、幂等写 |
| `src/kb/cli.py` | trace 子命令树挂 `snapshot` 分支 |
| `src/kb/serve.py` | 挂 `GET /api/metrics` 只读端点(仿 /api/trend 模式) |
| 面板 HTML | "周趋势"区块(折线×3 + 柱×1 + 占位态) |
| `tests/` | §6 各分支; 兼容回归先行 |

不在范围内(YAGNI): 自动写库工单、月度自动深分析报告(期末人工 diff 快照即可)、
面板改动 R6 既有逻辑、任何对 stats.py 口径的修改。
