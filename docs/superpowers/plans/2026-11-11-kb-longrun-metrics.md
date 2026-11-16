# 长周期运行指标(周快照 + 消化回路)实施计划

> **For agentic workers**: REQUIRED SUB-SKILL — 用 `superpowers:subagent-driven-development`(推荐)或 `superpowers:executing-plans` 按任务逐个执行。每个步骤 2-5 分钟；每个代码块都是可直接落盘的最终代码，**禁止 TBD / "同 Task N" / 无代码的测试步骤**。

**目标**: 把一个自然周(ISO 周一~周日)已验证口径的检索指标凝固成不可变快照 `traces/metrics/YYYY-Www.json`，配 CLI 周报(环比 + 消化工单建议)、`GET /api/metrics` 只读端点与面板"周趋势"区，让长周期观测有稳定分母、消化工单有跨周账本。

**架构**: 方案 A —— **指标零新计算**，全部委托 `src/kb/stats.py`(`aggregate`/`latency`/`zero_hit_board`/`callers`)；新计算层只有一个 `src/kb/metrics.py`(切周/编排/幂等落盘/读取/环比/工单建议)，CLI、serve、面板都只是消费方。已批准 spec：`docs/superpowers/specs/2026-11-11-kb-longrun-metrics-design.md`。

**技术栈**: Python 3.12(stdlib only)、argparse、http.server、单文件原生 JS 面板、pytest。

## Global Constraints

- 回复与代码注释用**中文**；注释只解释"为什么"。
- PowerShell 不支持 `&&`，用 `;`。测试命令(仓根执行)：`.venv\Scripts\python.exe -m pytest tests/test_xxx.py -q`。
- **快照幂等红线**：已存在的周文件拒绝覆盖(退 1)，`--force` 才重写；快照是唯一事实源，不回算不修改。
- **消化工单只出建议、零写库**；落库必须走 `kb new` / `kb review` 门控(AGENTS.md 红线)。
- 面板"周趋势"是**只读消费方**，不做任何指标运算；R6 瞬时窗口能力零回归。
- 提交纪律：仓内还有与本特性无关的未提交文件，**禁止 `git add -A` / `git add .`**，每个 commit 只显式列本任务改动路径。
- **serve 热重载红线**：观测面板 `src/kb/web/index.html` 由运行中的 serve 进程持有缓存，Task 5 后必须重启 serve 才能看到新面板；**只允许重启 `127.0.0.1` 回环实例，严禁按记忆去重启 `0.0.0.0:4320`**（该地址属另一会话、用户已明确"保持现状"）。

## 已核实的事实基线(执行者不必重查)

- `src/kb/stats.py`：`aggregate(searches, gets, *, since, until)` L262 → 含 `searches/hit_rate/consume_rate/cold_start`；`latency(searches, *, since, until)` L304 → 空输入 `{"n":0,...None}`；`zero_hit_board(searches, *, limit=10) -> list[dict]` L394(**单参返回列表，行内 `digested` 布尔；report 分支 L481-482 即 `board = ...; digested = [r for r in board if r["digested"]]` 用法**)；`callers(searches, *, since, until)` L489(**不存在 `callers_matrix`，spec 行文按真实名理解**)；`denoise(searches, gets) -> (s, g, n, bad)` L107；`in_window(events, since, until)` L146。
- `src/kb/trace.py`：`read_traces(root, *, caller, since, zero_hit, limit) -> (searches, gets, warns)`；`_iter_raw` L346 只对 `traces/` 根 `glob("*.jsonl")` → `traces/metrics/*.json` 天然不被吞(子目录+后缀双保险)；`traces_dir(root)` = `root/traces`；`append_event(ev, root=...)`。pytest 会话内埋点只写临时目录(trace_enabled 红线)，root 传 tmp_path 即正常落盘。
- `src/kb/cli.py`：`main(argv) -> int`；trace 子命令树 L160-190(`tr_sub.add_parser(...)`，各带 `--repo default=None`，**不用 parents=[common]**)；`_date_arg` L25 起(argparse 入口即拒)；report 分支 L475-501，`if args.trace_cmd == "show"` 在 L502 —— **snapshot 分支插在 L501 `return 0` 与 L502 之间**；分支内已有变量 `root`(=repo)、模块级 `json` 可用；分支内局部导入风格 `from kb import stats as kbstats`。
- `src/kb/serve.py`：`ServeServer(("127.0.0.1",0), root, token, default_caller, quiet=True)`，`srv.root` 可用；端点挂载：`/api/trend` L468-471 走 `srv.agg.get(ck, ...)`，`/api/export` L472 起直连；`q = parse_qs(u.query)`(取参 `q.get("k", [""])[0]`)；`self._json(payload)`；**`AggCache._sig` 只盯 `traces/*.jsonl` → 新快照 `.json` 不会使其失效，`/api/metrics` 必须直连不走 agg**；顶部导入现为 `from kb import stats, trace as kbtrace`。
- 面板 `src/kb/web/index.html`(**不在 assets/**)：趋势卡 L248-251(新卡插 L251 之后)；工具函数 `apiUrl` L374、`fetchT(url,ms=15000)` L377、`fetchErr(e)` L382、`$=id=>document.getElementById(id)` L327、`esc` L328、CSS 变量 `--warn`；装载行 L1258：`loadStats(); loadQuality(); loadFeed(); loadTrend(); stream(); if(view==='fed')loadMatrix();`。
- 测试样板：`tests/test_trace_command.py` L9-22 —— `env` fixture(monkeypatch `trace.kb_root` → `tmp_path/agent-kb`)、`_seed(root)`、调用 `main(["trace","list"])`；`tests/test_stats_serve.py` L397-419 —— `_serve(tmp_path)` → `(srv, base_url)`(内部 `(tmp_path/"traces").mkdir(exist_ok=True)`)、`_get_url(url)` → `(status, json)`、`_get_any(url)`(非 2xx 也返回体)。
- `kb/search.py`：`search(repo_root, ..., query=None, limit=20) -> list[dict]` L181(evaluate 的 limit 包装)——**纯函数无副作用**(不写埋点)；索引 `<repo>/kb/index.jsonl` 不存在 → `[]`(工单退化为"立新条")。
- ISO 周算术(已手算核对)：2026-W45 = 11-02(一)~11-08(日)；2026-11-11 属 W46；2026 年 53 周(2027-W01 上一周 = 2026-W53)；2026-W01 上一周 = 2025-W52。
- `scripts/commit-traces.sh`(22 行)：`set -e`；master 检查 L9-13；**L15 porcelain 空转检查、L20 `git add traces/`(已覆盖 metrics/ 子目录)** → 周一生成步骤必须插在 **L15 之前**，快照才能进同一次提交。

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `src/kb/metrics.py` | 新增 | 周号解析/切窗聚合/幂等落盘/读取/环比/工单建议 |
| `tests/test_metrics.py` | 新增 | 上述纯函数 + 落盘单测 |
| `tests/test_trace_command.py` | 修改 | 兼容回归：read_traces 不吞 `traces/metrics/` |
| `src/kb/cli.py` | 修改 | `_week_arg` + `trace snapshot` 子命令与分支 |
| `tests/test_trace_snapshot.py` | 新增 | CLI 端到端(幂等/格式/工单/默认周) |
| `src/kb/serve.py` | 修改 | `GET /api/metrics` 直连端点 |
| `tests/test_stats_serve.py` | 修改 | 端点空/正常/坏文件三态 |
| `src/kb/web/index.html` | 修改 | "周趋势"卡 + `loadWeek()` |
| `scripts/commit-traces.sh` | 修改 | 周一顺带生成上周快照(失败仅告警) |

---

### Task 1: 兼容回归 —— read_traces 不吞 `traces/metrics/`

spec §2 要求实施第一步固化该性质(静态已证实：`_iter_raw` 只 glob `*.jsonl`)，测试锁死未来 glob/后缀改动。

**Files**: Modify `tests/test_trace_command.py`(末尾追加，复用既有 `env`/`_seed`)

- [ ] **Step 1: 追加测试**

```python
def test_read_traces_ignores_metrics_subdir(env):
    """spec §2 兼容红线: traces/metrics/YYYY-Www.json 是快照落盘位, 必须被
    read_traces 忽略——_iter_raw 只对 traces/ 根 glob("*.jsonl"), 子目录与
    .json 后缀双保险。此测试锁死该性质: 日后改成 rglob 或换后缀立即失败。"""
    _seed(env)
    before = trace.read_traces(root=env)
    assert before[0], "前置: _seed 应有可读物理事件"
    d = env / "traces" / "metrics"
    d.mkdir(parents=True)
    (d / "2026-W45.json").write_text('{"schema":1,"week":"2026-W45"}', encoding="utf-8")
    (d / "decoy.jsonl").write_text('{"kind":"search","trace_id":"t-ghost"}\n', encoding="utf-8")
    after = trace.read_traces(root=env)
    assert [e.get("trace_id") for e in after[0]] == [e.get("trace_id") for e in before[0]]
    assert after[2] == before[2]  # warns 不得多报(快照不是坏行)
```

- [ ] **Step 2: 运行**

`.venv\Scripts\python.exe -m pytest tests/test_trace_command.py -q`
预期 **PASS**(性质固化，非红灯驱动)。若 FAIL：兼容假设已被破坏，停下修实现，**不得删测试绕过**。

- [ ] **Step 3: 提交**

```powershell
git add tests/test_trace_command.py
git commit -m "test(trace): 固化 read_traces 不吞 traces/metrics/ 的兼容性质"
```

---

### Task 2: `src/kb/metrics.py` —— 快照计算与落盘层

**Files**: Create `src/kb/metrics.py`、Create `tests/test_metrics.py`

- [ ] **Step 1: 写失败测试** `tests/test_metrics.py`

```python
"""周指标快照层单测: 周号算术 / 切窗聚合 / 幂等落盘 / 环比 / 消化工单建议。"""
import datetime as dt
import json

import pytest

from kb import metrics
from kb import trace


def _search(tid, caller, query, returned, ts):
    # layers.scanned=5: 避开 stats.synthetic_callers 的"全部≤2 判合成"剔噪
    return {"kind": "search", "trace_id": tid, "ts": ts, "source": "cli",
            "caller_repo": caller, "query": query, "returned": returned,
            "duration_ms": 10,
            "layers": [{"repo": "kb", "scanned": 5,
                        "rejected": {"filter": 0, "query": 4},
                        "matched": [{"id": i, "title": f"T{i}"} for i in returned],
                        "taken": len(returned), "truncated_at_limit": False}]}


def _get(tid, kid, caller, ts):
    return {"kind": "get", "trace_id": tid, "ts": ts, "id": kid,
            "caller_repo": caller, "status": "ok", "chars": 800}


def _seed_week(root, monday: dt.date):
    """周内 2 检索(1 命中 1 零命中)+ 1 消费; 周外(day+20) 1 检索。"""
    at = lambda n: (monday + dt.timedelta(days=n)).isoformat() + "T10:00:00+08:00"
    for e in [_search("t1", "alpha", "推流 死锁", ["k1"], at(0)),
              _search("t2", "alpha", "授权 台账", [], at(1)),
              _get("t1", "k1", "alpha", at(0)),
              _search("t3", "alpha", "css slash", ["k2"], at(20))]:  # 周外
        trace.append_event(e, root=root)


def test_week_bounds_and_rejects_garbage():
    assert metrics.week_bounds("2026-W45") == ("2026-11-02", "2026-11-08")
    for bad in ("2026-45", "2026-W54", "2026-W4", "garbage", "", None):
        with pytest.raises(ValueError):
            metrics.week_bounds(bad)


def test_prev_of_is_iso_year_aware():
    assert metrics.prev_of("2026-W45") == "2026-W44"
    assert metrics.prev_of("2027-W01") == "2026-W53"   # 2026 是 53 周年
    assert metrics.prev_of("2026-W01") == "2025-W52"


def test_prev_week_default_is_previous_iso_week():
    assert metrics.prev_week(dt.date(2026, 11, 11)) == "2026-W45"  # 11-11 属 W46


def test_build_snapshot_window_and_schema(tmp_path):
    _seed_week(tmp_path, dt.date.fromisocalendar(2026, 45, 1))
    snap = metrics.build_snapshot(tmp_path, "2026-W45")
    assert set(snap) >= {"schema", "week", "since", "until", "generated_at",
                         "metrics", "latency", "zero_hit", "callers", "warns"}
    assert snap["schema"] == 1
    assert (snap["since"], snap["until"]) == ("2026-11-02", "2026-11-08")
    m = snap["metrics"]
    assert m["searches"] == 2                         # 周外 t3 不进分母
    assert m["hit_rate"] == 0.5                       # t1 命中 t2 零命中
    assert m["consume_rate"] == 1.0                   # 周内唯一返回条目被 get
    assert snap["latency"]["n"] == 2                  # 有 duration_ms 样本
    zh = snap["zero_hit"]
    assert [r["query"] for r in zh["board"]] == ["授权 台账"]
    assert zh["digested"] == 0 and zh["digest_rate"] == 0.0
    assert snap["callers"][0]["caller"] == "alpha"
    assert snap["warns"] == []


def test_write_snapshot_is_idempotent(tmp_path):
    _seed_week(tmp_path, dt.date.fromisocalendar(2026, 45, 1))
    snap = metrics.build_snapshot(tmp_path, "2026-W45")
    p = metrics.write_snapshot(tmp_path, snap)
    assert p.exists() and p.name == "2026-W45.json"
    with pytest.raises(FileExistsError):              # 幂等红线: 已存在拒覆盖
        metrics.write_snapshot(tmp_path, snap)
    assert metrics.write_snapshot(tmp_path, snap, force=True) == p


def test_load_snapshots_sorts_and_skips_broken(tmp_path):
    d = tmp_path / "traces" / "metrics"
    d.mkdir(parents=True)
    (d / "2026-W46.json").write_text('{"schema":1,"week":"2026-W46"}', encoding="utf-8")
    (d / "2026-W45.json").write_text('{"schema":1,"week":"2026-W45"}', encoding="utf-8")
    (d / "2026-W47.json").write_text("{坏的 json", encoding="utf-8")
    (d / "2026-W48.json").write_text('{"schema":1}', encoding="utf-8")   # 缺 week
    snaps, warns = metrics.load_snapshots(tmp_path)
    assert [s["week"] for s in snaps] == ["2026-W45", "2026-W46"]        # 排序+跳坏
    assert len(warns) == 2 and all("2026-W4" in w for w in warns)


def test_load_snapshots_empty_root(tmp_path):
    assert metrics.load_snapshots(tmp_path) == ([], [])


def test_delta_two_branches():
    cur = {"metrics": {"hit_rate": 0.8, "consume_rate": 0.5, "searches": 10},
           "zero_hit": {"digest_rate": 0.25}, "latency": {"p50_ms": 120}}
    prev = {"metrics": {"hit_rate": 0.6, "consume_rate": 0.5, "searches": 4},
            "zero_hit": {"digest_rate": 0.5}, "latency": {"p50_ms": 100}}
    d = metrics.delta(cur, prev)
    assert d["hit_rate"] == {"cur": 0.8, "prev": 0.6, "diff": 0.2}
    assert d["consume_rate"]["diff"] == 0.0
    assert d["digest_rate"]["diff"] == -0.25
    d2 = metrics.delta(cur, None)                     # 上周快照缺失 → 只报绝对值
    assert d2["hit_rate"] == {"cur": 0.8, "prev": None, "diff": None}


def test_digest_plan_prefers_existing_then_novels(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "index.jsonl").write_text(json.dumps({
        "id": "kb-20261012-7f3a", "title": "Vite HMR 失效排查", "type": "pitfall",
        "domain": "frontend", "scope": "stack", "status": "accepted",
        "confidence": "verified", "tags": ["vite", "hmr"], "keywords": [],
        "summary": "HMR 不刷新的根因", "path": "kb/pitfall/frontend/vite-hmr.md"},
        ensure_ascii=False), encoding="utf-8")
    snap = {"zero_hit": {"board": [
        {"query": "vite", "count": 3, "caller": "alpha",
         "last_ts": "2026-11-03T10:00:00+08:00", "digested": False},
        {"query": "推流 死锁 rtmp", "count": 2, "caller": "alpha",
         "last_ts": "2026-11-04T10:00:00+08:00", "digested": False},
        {"query": "已消化词", "count": 1, "digested": True}]}}
    plan = metrics.digest_plan(tmp_path, snap)
    # 已消化不进清单; "vite" 应命中索引(title/tags), 无匹配的退"立新条"
    assert [p["query"] for p in plan] == ["vite", "推流 死锁 rtmp"]
    by_q = {p["query"]: p for p in plan}
    assert by_q["vite"]["targets"] and "tags" in by_q["vite"]["action"]
    assert by_q["推流 死锁 rtmp"]["targets"] == []
    assert "立新条" in by_q["推流 死锁 rtmp"]["action"]
    # 若评分面意外零命中致断言失败: 调整的是索引 fixture 的 tags/title 用词, 不改实现


def test_digest_plan_without_index(tmp_path):
    """空仓(无 kb/index.jsonl)不炸: 全部退化为"立新条"。"""
    plan = metrics.digest_plan(tmp_path, {"zero_hit": {"board": [
        {"query": "x y", "count": 1, "digested": False}]}})
    assert plan[0]["action"].startswith("立新条")


def test_report_markdown_shows_delta_and_ticket():
    cur = {"schema": 1, "week": "2026-W45", "since": "2026-11-02",
           "until": "2026-11-08",
           "metrics": {"searches": 10, "hit_rate": 0.8, "consume_rate": 0.5,
                       "cold_start": False},
           "latency": {"n": 8, "p50_ms": 120, "p95_ms": 400, "avg_ms": 150,
                       "max_ms": 700},
           "zero_hit": {"board": [{"query": "vite hmr", "count": 3,
                                   "caller": "alpha",
                                   "last_ts": "2026-11-03T10:00:00+08:00",
                                   "digested": False}],
                        "digested": 0, "digest_rate": 0.0},
           "callers": [{"caller": "alpha", "searches": 10, "hit_rate": 0.8,
                        "last_ts": "2026-11-08T10:00:00+08:00", "stale": False}],
           "warns": []}
    prev = {"metrics": {"searches": 4, "hit_rate": 0.6, "consume_rate": 0.5},
            "zero_hit": {"digest_rate": 0.5}, "latency": {"p50_ms": 100}}
    md = metrics.report_markdown(cur, prev, [
        {"query": "vite hmr", "count": 3,
         "action": "补 tags(中英各一组) / 改 summary",
         "targets": [{"id": "kb-20261012-7f3a", "title": "Vite HMR 失效排查"}]}])
    assert "2026-W45" in md and "2026-11-02" in md
    assert "+20.0pp" in md                            # 命中率环比
    assert "kb-20261012-7f3a" in md                   # 工单指向目标条目 id
    md2 = metrics.report_markdown(cur, None, [])
    assert "上周快照缺失" in md2                       # 环比缺失分支如实标注
```

- [ ] **Step 2: 运行确认失败**

`.venv\Scripts\python.exe -m pytest tests/test_metrics.py -q`
预期：`ModuleNotFoundError: No module named 'kb.metrics'`(collection error 即红灯成立)。

- [ ] **Step 3: 写实现** `src/kb/metrics.py`

```python
"""周指标快照层 — 长周期观测的凝固点。

设计: docs/superpowers/specs/2026-11-11-kb-longrun-metrics-design.md(方案 A)

职责边界:
- 指标口径**零新计算**, 全部委托 kb.stats(唯一实现), 本模块只做切周/编排/落盘/读取;
- 快照落 traces/metrics/YYYY-Www.json, 是不可变账本: 已存在即拒绝重写(--force 除外),
  否则"上周报的命中率"会在下周变成另一个数, 长周期趋势失去意义;
- 消化工单只产出**建议清单**, 零写库: 落库必须走 kb new / kb review 门控(AGENTS.md 红线)。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from kb import search as kbsearch
from kb import stats
from kb import trace as kbtrace

SCHEMA = 1
_BOARD_LIMIT = 30      # 与 kb trace report 的榜单上限一致
_PLAN_LIMIT = 10       # 工单清单上限(周报可读性优先, 全量走快照 JSON 自查)

# 周号严格 YYYY-Www: `2026-45`/`2026-W4` 会被静默错解成别的周,
# 与 cli._date_arg 同族的"入口即拒"原则 —— 不把坏值放进数据面。
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def week_bounds(week: str) -> tuple[str, str]:
    """`YYYY-Www` → (周一, 周日) ISO 日期串。非法值 ValueError(调用面在 argparse 即拒)。"""
    m = _WEEK.match(week or "")
    if not m:
        raise ValueError(f"需 YYYY-Www 周号(如 2026-W45), 收到 {week!r}")
    y, w = int(m.group(1)), int(m.group(2))
    try:
        mon = dt.date.fromisocalendar(y, w, 1)
        sun = dt.date.fromisocalendar(y, w, 7)
    except ValueError:
        raise ValueError(f"非法 ISO 周: {week!r}") from None
    return mon.isoformat(), sun.isoformat()


def prev_of(week: str) -> str:
    """上一 ISO 周号。周一回推 3 天必落在上一周(周日)→ isocalendar 天然跨年/跨 53 周。"""
    mon = dt.date.fromisoformat(week_bounds(week)[0])
    y, w, _ = (mon - dt.timedelta(days=3)).isocalendar()
    return f"{y}-W{w:02d}"


def prev_week(today: dt.date | None = None) -> str:
    """默认口径: 上一个**完整**自然周(本周还没跑完, 拿它出周报是半窗数据)。"""
    y, w, _ = (today or dt.date.today()).isocalendar()
    return prev_of(f"{y}-W{w:02d}")


def metrics_dir(root: Path | None = None) -> Path:
    return kbtrace.traces_dir(root) / "metrics"


def snapshot_path(root: Path | None, week: str) -> Path:
    return metrics_dir(root) / f"{week}.json"


def build_snapshot(root: Path | None, week: str) -> dict:
    """聚合某自然周的指标(口径全在 stats)。入参先过 denoise —— 与面板/KPI 同口径,
    否则快照会把 pytest 合成语料算进分母(2026-11-02 实测污染 25%)。"""
    since, until = week_bounds(week)
    searches, gets, warns = kbtrace.read_traces(root)
    searches, gets, _n, _bad = stats.denoise(searches, gets)
    win_s = stats.in_window(searches, since, until)
    win_g = stats.in_window(gets, since, until)
    board = stats.zero_hit_board(win_s, limit=_BOARD_LIMIT)
    dig = [r for r in board if r.get("digested")]
    return {
        "schema": SCHEMA,
        "week": week,
        "since": since,
        "until": until,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "metrics": stats.aggregate(win_s, win_g, since=since, until=until),
        "latency": stats.latency(win_s, since=since, until=until),
        "zero_hit": {"board": board, "digested": len(dig),
                     "digest_rate": round(len(dig) / len(board), 4) if board else None},
        "callers": stats.callers(win_s, since=since, until=until),
        "warns": warns,
    }


def write_snapshot(root: Path | None, snap: dict, *, force: bool = False) -> Path:
    """落盘。已存在且未 force → FileExistsError(CLI 转成退 1 + 人话)。"""
    p = snapshot_path(root, snap["week"])
    if p.exists() and not force:
        raise FileExistsError(
            f"快照已存在(不可变账本): {p}\n"
            f"  确要按当前账本重写请加 --force(会改变历史周报口径, 需在评审说明)")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def load_snapshots(root: Path | None) -> tuple[list[dict], list[str]]:
    """读全部周快照, 按周号升序。坏文件跳过并计 warns —— 一个手改坏的快照
    不该让整条趋势线与 /api/metrics 500(stats §26/§50 同族教训)。"""
    d = metrics_dir(root)
    if not d.exists():
        return [], []
    out: list[dict] = []
    warns: list[str] = []
    for f in sorted(d.glob("*.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:   # JSONDecodeError 是 ValueError 子类
            warns.append(f"{f.name}: 快照不可读({exc}), 已跳过")
            continue
        if not isinstance(obj, dict) or not obj.get("week"):
            warns.append(f"{f.name}: 缺 week 字段, 已跳过")
            continue
        out.append(obj)
    out.sort(key=lambda o: str(o["week"]))
    return out, warns


# 环比字段: (展示名, 取值路径)。任一侧非数值 → diff=None(只报绝对值, 不猜)。
_DELTA_SPEC = (("searches", ("metrics", "searches")),
               ("hit_rate", ("metrics", "hit_rate")),
               ("consume_rate", ("metrics", "consume_rate")),
               ("digest_rate", ("zero_hit", "digest_rate")),
               ("p50_ms", ("latency", "p50_ms")))


def _pick(snap: dict | None, path: tuple[str, str]):
    v = (snap or {}).get(path[0], {})
    v = v.get(path[1]) if isinstance(v, dict) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def delta(cur: dict, prev: dict | None) -> dict:
    """环比: {name: {cur, prev, diff}}。上周快照缺失/该字段无值 → diff=None。"""
    out = {}
    for name, path in _DELTA_SPEC:
        c = _pick(cur, path)
        p = _pick(prev, path) if prev else None
        out[name] = {"cur": c, "prev": p,
                     "diff": None if (c is None or p is None) else round(c - p, 4)}
    return out


def digest_plan(root: Path | None, snap: dict, *, limit: int = _PLAN_LIMIT) -> list[dict]:
    """消化工单**建议**: 未消化零命中词 → 用同一检索面(kb.search, 纯函数无副作用)
    找近似条目。有近似命中 = 词能命中库面但排序/字段没接上 → 补 tags(中英各一组) /
    改 summary; 无近似命中 = 库里确实没答案 → 立新条。

    红线: 本函数不写任何东西。落库由人/agent 走 `kb new --generated`(draft)与
    `kb review`(accepted 须 evidence + confidence 提升), 且追加"新发现"必须同步补 tags。
    """
    plan: list[dict] = []
    for r in (snap.get("zero_hit", {}).get("board") or []):
        if r.get("digested") or len(plan) >= limit:
            continue
        q = str(r.get("query") or "")
        note = ""
        try:
            hits = kbsearch.search(Path(root) if root else kbtrace.kb_root(),
                                   query=q, limit=3)
        except (OSError, ValueError) as exc:
            # 索引缺失/损坏不是错误, 是"库里没有可挂靠条目"这一事实的一部分
            hits, note = [], f"(索引不可用: {exc})"
        if hits:
            action = "补 tags(中英各一组) / 改 summary, 让该词接上既有条目" + note
            targets = [{"id": h.get("id"), "title": h.get("title")} for h in hits]
        else:
            action = "立新条(kb new, 先 kb search 去重)" + note
            targets = []
        plan.append({"query": q, "count": r.get("count"), "caller": r.get("caller"),
                     "last_ts": r.get("last_ts"), "action": action, "targets": targets})
    return plan


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def report_markdown(snap: dict, prev: dict | None = None,
                    plan: list[dict] | None = None) -> str:
    """周报正文(stdout 展示物, 快照本身不含它)。环比缺失必须**显式标注**——
    沉默的"—"会被读成"没变化"(§58 假数据同族)。"""
    m = snap.get("metrics") or {}
    zh = snap.get("zero_hit") or {}
    la = snap.get("latency") or {}
    d = delta(snap, prev)

    def pp(name: str) -> str:
        v = d[name]["diff"]
        return "环比 —(上周快照缺失)" if v is None \
            else f"环比 {'+' if v >= 0 else ''}{v * 100:.1f}pp"

    def ms(name: str) -> str:
        v = d[name]["diff"]
        return "环比 —(上周快照缺失)" if v is None \
            else f"环比 {'+' if v >= 0 else ''}{v:.0f}ms"

    cold = " · ⚠ 冷启动(样本 <3, 比率不稳)" if m.get("cold_start") else ""
    out = [f"# 知识库周指标 · {snap.get('week')}({snap.get('since')} ~ {snap.get('until')})",
           "",
           f"- 检索 **{m.get('searches') or 0}** 次 · 命中率 **{_pct(m.get('hit_rate'))}**"
           f"({pp('hit_rate')}){cold}",
           f"- 返回→消费率 **{_pct(m.get('consume_rate'))}**({pp('consume_rate')})"
           f" · 零命中消化率 **{_pct(zh.get('digest_rate'))}**({pp('digest_rate')})"]
    out.append(f"- 检索耗时 p50 {la.get('p50_ms')}ms / p95 {la.get('p95_ms')}ms(n={la.get('n')}) {ms('p50_ms')}"
               if la.get("n") else "- 检索耗时: 本周无 duration_ms 样本")
    out += ["", "## 活跃项目"]
    rows = snap.get("callers") or []
    if not rows:
        out.append("- 本周无检索活动")
    for r in rows[:10]:
        out.append(f"- `{r.get('caller')}`: {r.get('searches')} 次 · 命中率 "
                   f"{_pct(r.get('hit_rate'))}"
                   + (" · ⚠ 超 14 天无活动" if r.get("stale") else ""))
    out += ["", "## 消化工单(仅建议 · 落库走 kb new / kb review 门控)"]
    if plan:
        for it in plan:
            tg = "、".join(f"{t['id']}「{t['title']}」" for t in it["targets"]) or "无"
            out.append(f"- 「{it['query']}」×{it['count']}(caller={it.get('caller')}, "
                       f"最近 {str(it.get('last_ts'))[:10]})\n"
                       f"  - 建议: {it['action']}\n  - 候选条目: {tg}")
    else:
        out.append("- 本周待消化零命中: 无 ✅")
    if snap.get("warns"):
        out += ["", f"> ⚠ 读侧告警 {len(snap['warns'])} 条(不影响本表口径): "
              + "; ".join(str(w) for w in snap["warns"][:3])]
    return "\n".join(out)
```

- [ ] **Step 4: 运行至全绿**

`.venv\Scripts\python.exe -m pytest tests/test_metrics.py -q` → 全 PASS。
再跑既有回归确认无耦合破坏：`.venv\Scripts\python.exe -m pytest tests/test_stats_serve.py tests/test_trace_command.py -q`

- [ ] **Step 5: 提交**

```powershell
git add src/kb/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): 周指标快照计算与幂等落盘层"
```

---

### Task 3: `kb trace snapshot` —— 落盘 + 周报 + 工单建议

**Files**: Modify `src/kb/cli.py`(三处：`_date_arg` 之后加 `_week_arg`；L190 之后加子命令；L501/L502 之间加分支)、Create `tests/test_trace_snapshot.py`

- [ ] **Step 1: 写失败测试** `tests/test_trace_snapshot.py`

```python
"""kb trace snapshot 端到端: 落盘+周报 / 幂等退 1 / --force / json 格式 / 默认上一周。"""
import datetime as dt
import json

import pytest

from kb import metrics
from kb import trace
from kb.cli import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    """有账本的仓根: 2026-W45 周内 2 检索(1 命中 1 零命中)+ 1 消费。"""
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    at = lambda n: (dt.date.fromisocalendar(2026, 45, 1)
                    + dt.timedelta(days=n)).isoformat() + "T10:00:00+08:00"
    for ev in [
        {"kind": "search", "trace_id": "t-4501", "ts": at(0), "source": "cli",
         "caller_repo": "alpha", "query": "vite hmr", "duration_ms": 10,
         "returned": ["kb-1"],
         "layers": [{"repo": "kb", "scanned": 120,
                     "rejected": {"filter": 0, "query": 119},
                     "matched": [{"id": "kb-1", "title": "T1"}],
                     "taken": 1, "truncated_at_limit": False}]},
        {"kind": "get", "trace_id": "t-4501", "ts": at(0), "id": "kb-1",
         "caller_repo": "alpha", "status": "ok", "chars": 900},
        {"kind": "search", "trace_id": "t-4502", "ts": at(1), "source": "mcp",
         "caller_repo": "beta", "query": "rtmp 断流", "duration_ms": 20,
         "returned": [],
         "layers": [{"repo": "kb", "scanned": 120,
                     "rejected": {"filter": 0, "query": 120}, "matched": [],
                     "taken": 0, "truncated_at_limit": False}]}]:
        trace.append_event(ev, root=root)
    return root


def test_snapshot_writes_and_reports(env, capsys):
    assert main(["trace", "snapshot", "--week", "2026-W45"]) == 0
    p = env / "traces" / "metrics" / "2026-W45.json"
    assert p.exists()
    snap = json.loads(p.read_text(encoding="utf-8"))
    assert snap["schema"] == 1 and snap["since"] == "2026-11-02"
    assert snap["metrics"]["searches"] == 2
    out = capsys.readouterr().out
    assert "知识库周指标 · 2026-W45" in out
    assert "消化工单" in out and "rtmp 断流" in out     # 未消化零命中进工单
    assert "上周快照缺失" in out                        # 无上周快照 → 环比显式标注


def test_snapshot_idempotent_refuses_and_force(env, capsys):
    assert main(["trace", "snapshot", "--week", "2026-W45"]) == 0
    capsys.readouterr()
    assert main(["trace", "snapshot", "--week", "2026-W45"]) == 1   # 幂等红线: 退 1
    assert "--force" in capsys.readouterr().err
    assert main(["trace", "snapshot", "--week", "2026-W45", "--force"]) == 0
    assert main(["trace", "snapshot", "--week", "2026-W01"]) == 0   # 空周也成立
    snap = json.loads((env / "traces" / "metrics" / "2026-W01.json")
                      .read_text(encoding="utf-8"))
    assert snap["metrics"]["searches"] == 0            # 空周如实出零, 不报错


def test_snapshot_json_format(env, capsys):
    assert main(["trace", "snapshot", "--week", "2026-W45",
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)      # stdout 必须是纯 JSON
    assert payload["schema"] == 1 and payload["week"] == "2026-W45"


def test_snapshot_bad_week_rejected_by_argparse(env):
    with pytest.raises(SystemExit):                    # 入口即拒, 不进业务面
        main(["trace", "snapshot", "--week", "2026-45"])


def test_snapshot_default_is_previous_iso_week(env, capsys, monkeypatch):
    # 默认周钉死为 W45(账本数据全在 W45): 不依赖用例运行日期。
    # 只测"默认周接线正确"(不传 --week → 用 prev_week 的返回值);
    # prev_week 自身的 ISO 算术由 test_metrics.py 独立覆盖。
    monkeypatch.setattr(metrics, "prev_week", lambda: "2026-W45")
    assert main(["trace", "snapshot"]) == 0
    assert (env / "traces" / "metrics" / "2026-W45.json").exists()
    assert "2026-W45" in capsys.readouterr().out
```

- [ ] **Step 2: 运行确认失败**

`.venv\Scripts\python.exe -m pytest tests/test_trace_snapshot.py -q`
预期：FAIL(`argument trace_cmd: invalid choice: 'snapshot'` 或等价 argparse 报错)。

- [ ] **Step 3: 实现 CLI 三处改动**

3a. `src/kb/cli.py` 在 `_date_arg` 函数之后新增：

```python
def _week_arg(s: str) -> str:
    """ISO 周号入口即拒(对齐 _date_arg): 坏周号不进业务面。"""
    from kb import metrics as _m
    try:
        _m.week_bounds(s)
    except ValueError as exc:
        raise argparse.ArgumentError(None, str(exc)) from None
    return s
```

3b. L190(`p_trp.add_argument("--format", ...)`)之后、`args = ap.parse_args(argv)` 之前新增子命令：

```python
    # 长周期观测: 自然周指标快照(不可变账本)+ 周报 + 消化工单建议
    p_tsn = tr_sub.add_parser("snapshot",
                              help="周指标快照(落盘 traces/metrics/ + 周报 + 消化工单建议)")
    p_tsn.add_argument("--repo", default=None,
                       help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_tsn.add_argument("--week", default=None, type=_week_arg,
                       help="YYYY-Www(如 2026-W45), 默认上一个完整自然周")
    p_tsn.add_argument("--force", action="store_true",
                       help="重写已存在的周快照(改变历史口径, 需在评审说明)")
    p_tsn.add_argument("--format", default="md", choices=["md", "json"],
                       help="md=周报正文(默认); json=快照原文(供脚本消费)")
```

3c. 在 report 分支 `return 0`(L501)与 `if args.trace_cmd == "show":`(L502)之间插入：

```python
        if args.trace_cmd == "snapshot":
            from kb import metrics as kbmetrics
            week = args.week or kbmetrics.prev_week()
            try:
                snap = kbmetrics.build_snapshot(root, week)
                path = kbmetrics.write_snapshot(root, snap, force=args.force)
            except FileExistsError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(snap, ensure_ascii=False, indent=2))
                return 0
            snaps, _w = kbmetrics.load_snapshots(root)
            prev = next((s for s in reversed(snaps)
                         if s.get("week") == kbmetrics.prev_of(week)), None)
            plan = kbmetrics.digest_plan(root, snap)
            print(kbmetrics.report_markdown(snap, prev, plan))
            print(f"\n快照已落盘: {path.relative_to(root) if root else path}")
            return 0
```

(`sys`/`json` 为 cli.py 模块级已有导入；分支内不重复 import。)

- [ ] **Step 4: 运行至全绿**

`.venv\Scripts\python.exe -m pytest tests/test_trace_snapshot.py tests/test_metrics.py -q` → 全 PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/kb/cli.py tests/test_trace_snapshot.py
git commit -m "feat(cli): kb trace snapshot 周指标快照与周报+消化工单建议"
```

---

### Task 4: `GET /api/metrics` —— 只读快照端点

**Files**: Modify `src/kb/serve.py`(L471 `/api/trend` 分支之后、`/api/export` 之前插入)、Modify `tests/test_stats_serve.py`(末尾追加)

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_stats_serve.py` 末尾，复用 `_serve`/`_get_url`)

```python
# ---- /api/metrics: 只读消费 traces/metrics/*.json --------------------------

def _snap(week, hit, searches, dig_rate, cold=False):
    return {"schema": 1, "week": week, "since": "2026-11-02", "until": "2026-11-08",
            "generated_at": "2026-11-09T18:30:00+08:00",
            "metrics": {"searches": searches, "hit_rate": hit, "consume_rate": 0.5,
                        "cold_start": cold},
            "latency": {"n": 5, "p50_ms": 120, "p95_ms": 400},
            "zero_hit": {"board": [], "digested": 0, "digest_rate": dig_rate},
            "callers": [], "warns": []}


def test_api_metrics_empty(tmp_path):
    srv, base = _serve(tmp_path)
    try:
        code, body = _get_url(f"{base}/api/metrics")
        assert code == 200 and body["snapshots"] == [] and body["warns"] == []
    finally:
        srv.shutdown()


def test_api_metrics_sorted_and_trimmed(tmp_path):
    d = tmp_path / "traces" / "metrics"
    d.mkdir(parents=True)
    (d / "2026-W46.json").write_text(json.dumps(_snap("2026-W46", 0.8, 10, 0.2)),
                                     encoding="utf-8")
    (d / "2026-W45.json").write_text(
        json.dumps(_snap("2026-W45", 0.6, 4, 0.5, cold=True)), encoding="utf-8")
    (d / "broken.json").write_text("{坏", encoding="utf-8")
    srv, base = _serve(tmp_path)
    try:
        code, body = _get_url(f"{base}/api/metrics")
        assert code == 200
        assert [s["week"] for s in body["snapshots"]] == ["2026-W45", "2026-W46"]
        assert len(body["warns"]) == 1                       # 坏文件跳过并上报
        # 点状字段白名单(面板只画这些), 完整 board 不回传(省带宽)
        pt = body["snapshots"][0]
        assert set(pt) == {"week", "since", "until", "searches", "hit_rate",
                           "consume_rate", "digest_rate", "p50_ms", "cold_start"}
        assert pt["cold_start"] is True
    finally:
        srv.shutdown()
```

- [ ] **Step 2: 运行确认失败**

`.venv\Scripts\python.exe -m pytest tests/test_stats_serve.py -q -k api_metrics`
预期：FAIL(404 → `_get_url` 抛 HTTPError)。

- [ ] **Step 3: 实现端点**

`src/kb/serve.py`：顶部导入行改为(加 `metrics`)：

```python
from kb import metrics as kbmetrics
from kb import stats, trace as kbtrace
```

在 `/api/trend` 分支(L471)之后、`elif u.path == "/api/export":`(L472)之前插入：

```python
            elif u.path == "/api/metrics":
                # 周快照直连不走 agg 缓存: AggCache._sig 只盯 traces/*.jsonl,
                # 新生成的 .json 快照不会使其失效 —— 走缓存会把"刚生成的上周快照"
                # 藏到 serve 重启为止。读盘是目录级小 IO, 面板轮询扛得住。
                snaps, warns = kbmetrics.load_snapshots(srv.root)
                points = []
                for s in snaps:
                    m = s.get("metrics") or {}
                    zh = s.get("zero_hit") or {}
                    la = s.get("latency") or {}
                    points.append({"week": s["week"], "since": s.get("since"),
                                   "until": s.get("until"),
                                   "searches": m.get("searches"),
                                   "hit_rate": m.get("hit_rate"),
                                   "consume_rate": m.get("consume_rate"),
                                   "digest_rate": zh.get("digest_rate"),
                                   "p50_ms": la.get("p50_ms"),
                                   "cold_start": bool(m.get("cold_start"))})
                self._json({"snapshots": points, "warns": warns})
```

- [ ] **Step 4: 运行至全绿**

`.venv\Scripts\python.exe -m pytest tests/test_stats_serve.py -q` → 全 PASS(含面板脚本解析守护)。

- [ ] **Step 5: 提交**

```powershell
git add src/kb/serve.py tests/test_stats_serve.py
git commit -m "feat(serve): GET /api/metrics 只读周快照端点(直连不走 agg 缓存)"
```

---

### Task 5: 面板"周趋势"区 —— 只读消费 /api/metrics

**Files**: Modify `src/kb/web/index.html`(两处：L251 `trendCard` 闭合后插新卡 HTML；L1258 装载行加 `loadWeek()`；L1239 `loadTrend` 函数闭合后加新函数)

- [ ] **Step 1: 插入卡片 HTML**

在 L251 `<div id="trend" style="overflow-x:auto"></div></div>`(trendCard 闭合)之后、L252 `<div class="card" id="matrixCard"...` 之前插入：

```html
<div class="card" id="weekCard"><h3>周趋势 <span class="tip">逐周快照(不可变账本) · 命中率/消费率/消化率三条折线 + 检索量柱 · 快照由 kb trace snapshot 每周一生成</span></h3>
  <div id="weekTrend" style="overflow-x:auto"></div></div>
```

- [ ] **Step 2: 插入 `loadWeek()` 函数**

在 L1239 `loadTrend` 的收尾 `}`(即 `}catch(e){/* 趋势失败不整卡报错, 保留上次曲线 */}\n}`)之后、L1240 `function conn(ok){...` 之前插入：

```js
// W1 周趋势: 只画 /api/metrics 的不可变周快照(与逐日瞬时窗口互补, 零前端计算)。
// 快照 <2 个画不出"趋势"(单点没有斜率), 显式占位而不是硬画 —— 冷启动期
// 用户需要知道"为什么没有", 沉默空白会被读成坏了(仿 loadTrend 冷启动占位)。
async function loadWeek(){
  const box=$('weekTrend');
  try{
    const r=await fetch('/api/metrics');
    if(r.status!=200)return;
    const d=await r.json();
    const snaps=(d.snapshots||[]).slice(-12);      // 最多 12 周, 老快照留在账本不挤面板
    if(snaps.length<2){box.innerHTML=
      '<div style="color:var(--mu);font-size:12px;padding:6px 0">周快照不足 2 个, 趋势暂不绘制(每周一自动生成, 或手动 kb trace snapshot 回补)</div>';return;}
    const pctLine=(key,color)=>{                 // 0~1 比率 → y 坐标折线
      const pts=snaps.map((s,i)=>s[key]==null?null:
        [8+56*i/(snaps.length-1),86-70*s[key]].join(','));
      const ok=pts.filter(p=>p);
      if(ok.length<2)return '';
      return `<polyline fill="none" stroke="${color}" stroke-width="1.6" points="${ok.join(' ')}"/>`;};
    const mx=Math.max(1,...snaps.map(s=>s.searches||0));
    const bars=snaps.map((s,i)=>{
      const h=Math.round(64*(s.searches||0)/mx);
      const x=8+56*i/(snaps.length-1);
      return `<rect x="${(x-2.4).toFixed(1)}" y="${(86-h).toFixed(1)}" width="4.8" height="${Math.max(1,h)}" fill="var(--trendoff)" opacity="0.5"><title>${esc(s.week)} · ${s.searches||0} 次检索</title></rect>`;}).join('');
    box.innerHTML=`<div style="min-width:340px"><svg viewBox="0 0 68 96" style="width:100%;height:130px" preserveAspectRatio="none">`
      +bars+pctLine('hit_rate','var(--ok)')+pctLine('consume_rate','var(--link)')
      +pctLine('digest_rate','var(--warn)')+`</svg>`
      +`<div style="display:flex;justify-content:space-between;font:9px Consolas,monospace;color:var(--mu)">`
      +snaps.map(s=>`<span${s.cold_start?' style="color:var(--warn)" title="冷启动周(样本<3), 比率不稳"':''}>${esc(String(s.week).slice(5))}</span>`).join('')+`</div>`
      +`<div class="s" style="font-size:11px;color:var(--mu)">━ <span style="color:var(--ok)">命中率</span> · ━ <span style="color:var(--link)">消费率</span> · ━ <span style="color:var(--warn)">消化率</span> · ▮ 检索量(悬停看精确值)</div>`
      +(d.warns&&d.warns.length?`<div style="font-size:11px;color:var(--warn)">⚠ 快照告警 ${d.warns.length} 条(坏文件已跳过)</div>`:'')
      +`</div>`;
  }catch(e){box.innerHTML=`<div style="color:var(--warn);font-size:12px;padding:4px 0">⚠ ${esc(fetchErr(e))}</div>`;}
}
```

- [ ] **Step 3: 接线装载**

L1258 改为(只加 `loadWeek()`)：

```js
  loadStats(); loadQuality(); loadFeed(); loadTrend(); loadWeek(); stream(); if(view==='fed')loadMatrix();
```

- [ ] **Step 4: 手动验证(浏览器)**

后台已有 serve(shell `9f0ab9c7...`, 0.0.0.0:4320)则先重启以加载新端点；造两份演示快照：

```powershell
.venv\Scripts\kb.exe trace snapshot --week 2026-W45 --repo .
.venv\Scripts\kb.exe trace snapshot --week 2026-W44 --repo .
```

打开 `http://127.0.0.1:4320/`：周趋势卡出现两条折线 + 柱；控制台零报错；删掉一个快照文件刷新后回退"快照不足 2 个"占位；`--` 验证 R6 瞬时窗口(逐日趋势/上一自然周按钮)不受影响。**验证产生的两份快照属于真实账本演示数据 —— 验证完删除这两个文件，勿提交。**

- [ ] **Step 5: 提交**

```powershell
git add src/kb/web/index.html
git commit -m "feat(web): 面板周趋势卡(只读消费 /api/metrics 周快照)"
```

---

### Task 6: 定时链路 —— 周一顺带生成上周快照

**Files**: Modify `scripts/commit-traces.sh`

- [ ] **Step 1: 修改脚本**

在 L13(`fi`，master 检查结束)与 L15(porcelain 空转检查)**之间**插入(必须在 `git add traces/` 之前，快照才进同一次每日提交)：

```sh
# 周一顺带生成上一自然周快照(kb trace snapshot 幂等: 已存在则仅提示不重写)。
# 失败只告警绝不阻断每日提交(set -e 下用 || 收敛): 快照是观测的下游消费,
# 它坏了不该让 traces 账本停更 —— 观测不拖垮任何事(serve 同款红线)。
if [ "$(date +%u)" = "1" ]; then
  if ! .venv/bin/kb trace snapshot --repo . >/dev/null 2>&1; then
    echo "commit-traces: ⚠ 周一快照生成失败(不阻断提交), 手动回补: kb trace snapshot --repo ." >&2
  fi
fi
```

(Windows 计划任务侧若用 `.bat`/PowerShell 触发本 sh，无需改动——脚本内部已自洽；若调度机是 Windows 且走 git-bash，`.venv/bin/kb` 即 shim 存在。)

- [ ] **Step 2: 静态验证**

`sh -n scripts/commit-traces.sh`(git-bash 语法检查)通过；肉眼核对：插入位置在 porcelain 检查之前、`--repo .` 在子命令之后(Global Constraints 的 CLI 顺序约定)。

- [ ] **Step 3: 提交**

```powershell
git add scripts/commit-traces.sh
git commit -m "chore(scripts): 每日 traces 提交在周一顺带生成上一周指标快照(失败仅告警)"
```

---

## 验收清单(全部任务完成后)

1. `.venv\Scripts\python.exe -m pytest -q` 全绿(含既有 ~500 用例零回归)。
2. `kb lint --scope agent-kb --repo .` 与 `kb index --check --repo .` 通过(本次不碰知识库条目, 应天然通过)。
3. `git log --oneline -7`：恰 6 个新 commit, 每个只含本任务文件。
4. 手动冒烟：`kb trace snapshot --week <上一周> --repo .` 出周报 + 落盘；重复执行退 1；`/api/metrics` 返回快照点；面板周趋势卡渲染；**演示快照事后删除不入库**。
5. spec 勘误(微小, 随 Task 2 commit 一并改)：spec §1 中 `callers_matrix` → `callers`、`zero_hit_board(searches, gets)` → `zero_hit_board(searches)` 单参列表返回, 以代码为准在 spec 原句旁加一行"(实施勘误: 实际签名 …)"注记。

## 自审记录(writing-plans 三查, 已执行)

1. **spec 覆盖**: §1 指标复用→Task2 build_snapshot；§2 快照 schema/幂等/兼容回归→Task1+Task2；§3 CLI 周报+环比+工单→Task3；§4 端点+面板+R6 保留→Task4+Task5；§5 定时→Task6；§6 测试清单逐项落在各任务(切窗/跨年 ISO 周、幂等、schema、兼容回归、环比两分支、工单启发式、端点空/坏文件、全程 tmp_path)；§7 改动面一致。
2. **占位符扫描**: 无 TBD/"类似 Task N"；所有测试与实现代码完整可落盘。已修正两处早期草稿残渣：`test_digest_plan` 的 `or True` 死断言行、Task3 默认周用例的 `_FixedDate` 脆弱桩(改 monkeypatch)。
3. **类型/命名一致性**: `zero_hit_board` 全计划统一"单参→list、行内 digested"；`callers()`(非 callers_matrix)；快照顶层键 `callers`；`load_snapshots→(list,warns)` 与端点/CLI 两处消费一致；`main(argv)->int` 与三个 CLI 测试一致。
