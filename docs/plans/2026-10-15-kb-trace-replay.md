# KB Trace 采集与 spider 回放 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `kb search` 与 MCP `kb_search`/`kb_get` 增加可选检索埋点，集中落盘 JSONL trace，并提供 `kb trace` 查看与 prompt-spider-ui 回放转换器。

**Architecture:** 三层插件式 — 采集层（`trace.py`，开关默认关闭、失败静默）→ 数据层（Agent-KB 仓根 `traces/*.jsonl`，schema 版本化，层间唯一耦合点）→ 消费层（`kb trace list/show/export`，未来可加 `kb web`）。检索内核改为"同时产出死因统计"，对外返回值零变化。

**Tech Stack:** Python ≥3.10，仅标准库（json / os / pathlib / datetime / uuid / argparse / time），pytest + pytest-asyncio（`asyncio_mode=auto`）。**不新增任何依赖。**

上游 spec：`docs/specs/2026-10-15-kb-trace-replay-design.md`

## Global Constraints

- trace 事件**绝不含知识正文**，只含 id / title / scope / confidence / summary 等元数据。
- 埋点任何异常（`OSError`）静默放弃 — 检索结果与退出码永不受影响。
- 开关默认**关闭**；关闭时行为与改造前完全一致（现有 118 条测试必须继续全绿）。
- `pyproject.toml` 不改，不引入第三方依赖。
- trace 落盘：Agent-KB 仓根 `traces/YYYY-MM-DD.jsonl`，自定位 = `Path(kb/trace.py).resolve().parents[2]`（kb → src → 仓根），Task 1 有断言 `kb_root()/pyproject.toml` 存在性兜底。
- `trace.SCHEMA = 1`；每个新文件首行写且仅写一次 `{"kind":"meta","schema":1}`。
- 死因恒等式：`rejected.filter + rejected.query + len(matched) == scanned`。
- `caller_repo` 一律 `Path(...).resolve().name.lower()`，与 index `repo` 字段同口径。
- 测试一律用 `tmp_path` 并显式传 `root=`，禁止读写真实 `traces/`。
- 每个 Task 收尾：`python -m pytest -q` 全量零 failed + `ruff check src tests` 干净，然后 commit。

---

### Task 1: trace 内核（开关 / 写入 / reader）

**Files:**
- Create: `src/kb/trace.py`
- Create: `tests/test_trace.py`
- Modify: `.gitignore`（追加 `traces/`）

**Interfaces:**
- Consumes: 无
- Produces:
  - `trace.SCHEMA: int`
  - `trace.kb_root() -> Path`
  - `trace.traces_dir(root: Path | None = None) -> Path`
  - `trace.trace_enabled(root: Path | None = None, cli_flag: bool | None = None) -> bool`
  - `trace.new_trace_id(ts: datetime | None = None) -> str`
  - `trace.append_event(event: dict, root: Path | None = None) -> None`
  - `trace.read_traces(root=None, *, caller=None, since=None, zero_hit=False, limit=None) -> tuple[list[dict], list[dict], list[str]]`（searches 最新在前, gets, warnings）
  - `trace.find_trace(trace_id: str, root=None) -> dict | None`
  - `trace.latest_search_id(caller_repo: str, root=None) -> str | None`

- [ ] **Step 1: 写失败测试（开关优先级）**

创建 `tests/test_trace.py`：

```python
import json
import pytest
from kb import trace


@pytest.fixture
def kbroot(tmp_path, monkeypatch):
    """Agent-KB 仓根指向 tmp, 隔离真实 traces/。"""
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    monkeypatch.delenv("KB_TRACE", raising=False)
    return root


def test_kb_root_points_to_repo_root():
    # src/kb/trace.py 的 parents[1] 必须是含 pyproject.toml 的仓根
    assert (trace.kb_root() / "pyproject.toml").exists()


def test_default_off(kbroot):
    assert trace.trace_enabled() is False


def test_cli_off_overrides_env_on(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "1")
    assert trace.trace_enabled(cli_flag=False) is False


def test_cli_on_overrides_env_off(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "0")
    assert trace.trace_enabled(cli_flag=True) is True


def test_env_on(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "1")
    assert trace.trace_enabled() is True


def test_env_zero_beats_marker(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "0")
    (kbroot / ".kb-trace").write_text("", encoding="utf-8")
    assert trace.trace_enabled() is False


def test_marker_file(kbroot):
    (kbroot / ".kb-trace").write_text("", encoding="utf-8")
    assert trace.trace_enabled() is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trace.py -q`
Expected: FAIL — `ImportError: cannot import name 'trace' from 'kb'`

- [ ] **Step 3: 实现开关 + 定位 + 写入**

创建 `src/kb/trace.py`：

```python
from __future__ import annotations
"""检索埋点采集层 — 开关控制 / append-only JSONL / 失败静默。

数据层唯一事实源: <Agent-KB 仓根>/traces/YYYY-MM-DD.jsonl。
spec §4.2 红线: 事件只含元数据+摘要, 绝不含正文; 写失败静默放弃。
"""
import datetime as dt
import json
import os
import uuid
from pathlib import Path

SCHEMA = 1
_MARKER = ".kb-trace"
_ENV = "KB_TRACE"
_FALSY = ("", "0", "false", "False", "no")


def kb_root() -> Path:
    # src/kb/trace.py → parents[0]=kb, [1]=src, [2]=仓根(submodule 挂载点即仓根)
    return Path(__file__).resolve().parents[2]


def traces_dir(root: Path | None = None) -> Path:
    return (Path(root) if root else kb_root()) / "traces"


def trace_enabled(root: Path | None = None, cli_flag: bool | None = None) -> bool:
    """优先级: CLI 显式 > KB_TRACE 环境变量 > 仓根 .kb-trace 标记 > 默认关闭。"""
    if cli_flag is not None:
        return cli_flag
    env = os.environ.get(_ENV)
    if env is not None:
        return env.strip() not in _FALSY
    base = Path(root) if root else kb_root()
    return (base / _MARKER).exists()


def new_trace_id(ts: dt.datetime | None = None) -> str:
    ts = ts or dt.datetime.now()
    return f"t-{ts:%Y%m%d}-{uuid.uuid4().hex[:4]}"


def _today_file(root: Path | None) -> Path:
    return traces_dir(root) / f"{dt.date.today():%Y-%m-%d}.jsonl"


def append_event(event: dict, root: Path | None = None) -> None:
    """行级 append, 新文件补 meta 行。任何 OSError 静默放弃。"""
    try:
        f = _today_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if not f.exists():
            lines.append(json.dumps({"kind": "meta", "schema": SCHEMA}, ensure_ascii=False))
        lines.append(json.dumps(event, ensure_ascii=False))
        with f.open("a", encoding="utf-8") as fh:
            fh.write("".join(ln + "\n" for ln in lines))
    except OSError:
        return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_trace.py -q`
Expected: `7 passed`

- [ ] **Step 5: 写失败测试（写入 + reader 四种降级 + 过滤）**

追加到 `tests/test_trace.py`：

```python
def _ev(i, kind="search", caller="web", returned=("kb-a",), ts="2026-10-15T14:32:05+08:00"):
    if kind == "get":
        return {"kind": "get", "trace_id": f"t-{i}", "ts": ts, "id": "kb-a",
                "layer": "docs", "ok": True, "source": "mcp", "caller_repo": caller}
    return {"kind": "search", "trace_id": f"t-{i}", "ts": ts, "source": "cli",
            "caller_repo": caller, "query": f"q{i}", "filters": {}, "limit": 10,
            "duration_ms": 3, "layers": [], "returned": list(returned)}


def _write(kbroot, name, lines):
    d = kbroot / "traces"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n"
                                  if not isinstance(x, str) else x + "\n"
                                  for x in lines), encoding="utf-8")
    return d


def test_new_file_writes_meta_once(kbroot):
    trace.append_event(_ev(1), root=kbroot)
    trace.append_event(_ev(2), root=kbroot)
    files = list((kbroot / "traces").glob("*.jsonl"))
    assert len(files) == 1                      # 同日单文件
    lines = files[0].read_text(encoding="utf-8").splitlines()
    metas = [ln for ln in lines if json.loads(ln).get("kind") == "meta"]
    assert len(metas) == 1
    assert json.loads(metas[0]) == {"kind": "meta", "schema": 1}
    assert len(lines) == 3


def test_read_splits_search_and_get(kbroot):
    trace.append_event(_ev(1), root=kbroot)
    trace.append_event(_ev(1, kind="get"), root=kbroot)
    searches, gets, warns = trace.read_traces(root=kbroot)
    assert [s["trace_id"] for s in searches] == ["t-1"]
    assert [g["trace_id"] for g in gets] == ["t-1"]
    assert warns == []


def test_read_missing_dir(kbroot):
    searches, gets, warns = trace.read_traces(root=kbroot)
    assert (searches, gets, warns) == ([], [], [])


def test_read_skips_file_without_meta(kbroot):
    _write(kbroot, "2026-01-01.jsonl", [_ev(9)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert searches == []
    assert any("meta" in w for w in warns)


def test_read_skips_future_schema(kbroot):
    _write(kbroot, "2026-01-02.jsonl", [{"kind": "meta", "schema": 99}, _ev(9)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert searches == []
    assert any("schema" in w for w in warns)


def test_read_skips_bad_line_and_warns(kbroot):
    _write(kbroot, f"{dt.date.today():%Y-%m-%d}.jsonl",
           [{"kind": "meta", "schema": 1}, _ev(1), "{ broken json", _ev(2)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert {s["trace_id"] for s in searches} == {"t-1", "t-2"}
    assert any("bad line" in w for w in warns)


def test_read_filters_and_ordering(kbroot):
    for i, caller in enumerate(["web", "algo", "web"]):
        ev = _ev(i, caller=caller, returned=())
        ev["ts"] = f"2026-10-1{i + 1}T10:00:00+08:00"
        trace.append_event(ev, root=kbroot)
    by_caller, _, _ = trace.read_traces(root=kbroot, caller="web")
    assert [s["trace_id"] for s in by_caller] == ["t-2", "t-0"]   # 最新在前
    zero, _, _ = trace.read_traces(root=kbroot, zero_hit=True)
    assert len(zero) == 3                                        # 三条 returned 均空
    limited, _, _ = trace.read_traces(root=kbroot, limit=2)
    assert len(limited) == 2
    since, _, _ = trace.read_traces(root=kbroot, since="2026-10-13")
    assert {s["trace_id"] for s in since} == {"t-2"}


def test_find_and_latest_search_id(kbroot):
    for i in range(3):
        ev = _ev(i, caller="web")
        ev["ts"] = f"2026-10-15T14:32:0{i+1}+08:00"   # 递增 ts, 排序可断言
        trace.append_event(ev, root=kbroot)
    assert trace.find_trace("t-1", root=kbroot)["query"] == "q1"
    assert trace.find_trace("nope", root=kbroot) is None
    assert trace.latest_search_id("web", root=kbroot) == "t-2"
    assert trace.latest_search_id("other", root=kbroot) is None
```

文件顶部 import 补一行 `import datetime as dt`（与既有 import 并列）。

- [ ] **Step 6: 跑测试确认新用例失败**

Run: `python -m pytest tests/test_trace.py -q`
Expected: FAIL — `AttributeError: module 'kb.trace' has no attribute 'read_traces'`

- [ ] **Step 7: 实现 reader**

追加到 `src/kb/trace.py`：

```python
def _iter_raw(root: Path) -> tuple[list[dict], list[dict], list[str]]:
    searches: list[dict] = []
    gets: list[dict] = []
    warns: list[str] = []
    d = traces_dir(root)
    if not d.exists():
        return searches, gets, warns
    for f in sorted(d.glob("*.jsonl")):
        lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            warns.append(f"{f.name}: 空文件, 跳过")
            continue
        try:
            meta = json.loads(lines[0])
        except json.JSONDecodeError:
            meta = {}
        if meta.get("kind") != "meta":
            warns.append(f"{f.name}: 缺 meta 首行, 跳过")
            continue
        if int(meta.get("schema", 0)) > SCHEMA:
            warns.append(f"{f.name}: schema={meta.get('schema')} 高于本地 {SCHEMA}, 跳过")
            continue
        for ln in lines[1:]:
            try:
                ev = json.loads(ln)
            except json.JSONDecodeError:
                warns.append(f"{f.name}: bad line 跳过")
                continue
            if ev.get("kind") == "search":
                searches.append(ev)
            elif ev.get("kind") == "get":
                gets.append(ev)
    return searches, gets, warns


def _newest_first(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: str(e.get("ts", "")), reverse=True)


def read_traces(root: Path | None = None, *, caller: str | None = None,
                since: str | None = None, zero_hit: bool = False,
                limit: int | None = None) -> tuple[list[dict], list[dict], list[str]]:
    base = Path(root) if root else kb_root()
    searches, gets, warns = _iter_raw(base)
    if caller:
        searches = [s for s in searches if s.get("caller_repo") == caller]
        gets = [g for g in gets if g.get("caller_repo") == caller]
    if since:
        searches = [s for s in searches if str(s.get("ts", ""))[:10] >= since]
    if zero_hit:
        searches = [s for s in searches if not s.get("returned")]
    searches, gets = _newest_first(searches), _newest_first(gets)
    if limit is not None:
        searches = searches[:limit]
    return searches, gets, warns


def find_trace(trace_id: str, root: Path | None = None) -> dict | None:
    searches, _, _ = _iter_raw(Path(root) if root else kb_root())
    return next((s for s in searches if s.get("trace_id") == trace_id), None)


def latest_search_id(caller_repo: str, root: Path | None = None) -> str | None:
    searches, _, _ = _iter_raw(Path(root) if root else kb_root())
    hits = _newest_first([s for s in searches if s.get("caller_repo") == caller_repo])
    return hits[0].get("trace_id") if hits else None
```

- [ ] **Step 8: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（原 118 + 新增约 16，零 failed）

- [ ] **Step 9: gitignore + 提交**

`.gitignore` 追加 `traces/`（放在既有生成物豁免项旁）。

```powershell
ruff check src tests
git add src/kb/trace.py tests/test_trace.py .gitignore
git commit -m "feat(trace): 采集层内核 - 开关判定/JSONL append/reader 降级"
```

---

### Task 2: 检索内核产出死因与命中字段

**Files:**
- Modify: `src/kb/search.py`（整文件替换）
- Create: `tests/test_search_eval.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `search.evaluate(repo_root, *, type=None, domain=None, tag=None, scope=None, status=None, confidence=None, query=None) -> tuple[list[dict], dict]`
    - `rows` 为**未按 limit 截断**的命中记录（与 `search()` 元素同形）
    - `report = {"scanned": int, "rejected": {"filter": int, "query": int}, "matched": [{"id","title","scope","confidence","hit_fields","hit_spans","rank"}]}`
  - `search.search(...)` 签名与返回**完全不变**（内部委派 `evaluate` 后截断）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_search_eval.py`：

```python
import json
import pytest
from kb import search


def _mk(tmp_path, recs):
    d = tmp_path / "kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return tmp_path


def _rec(i, title="nginx 413 body size", tags=("nginx", "upload"),
         summary="客户端 body 超限被 nginx 挡回", **over):
    r = {"id": f"kb-x{i}", "title": title, "type": "pitfall", "domain": ["frontend"],
         "tags": list(tags), "scope": "project", "status": "accepted",
         "confidence": "verified", "summary": summary,
         "path": f"kb/pitfall/frontend/x{i}.md", "updated": "2026-10-12", "repo": "web"}
    r.update(over)
    return r


def test_identity_holds(tmp_path):
    _mk(tmp_path, [_rec(i) for i in range(4)] + [_rec(90, title="vite hmr", tags=("vite",))])
    rows, rep = search.evaluate(tmp_path, query="vite")
    assert rep["scanned"] == 5
    assert rep["rejected"]["filter"] + rep["rejected"]["query"] + len(rep["matched"]) == 5
    assert [m["id"] for m in rep["matched"]] == ["kb-x90"]


def test_filter_rejection_counted(tmp_path):
    _mk(tmp_path, [_rec(1), _rec(2, type="howto")])
    rows, rep = search.evaluate(tmp_path, type="pitfall", query="nginx")
    assert rep["scanned"] == 2
    assert rep["rejected"] == {"filter": 1, "query": 0}
    assert [m["id"] for m in rep["matched"]] == ["kb-x1"]


def test_query_rejection_counted(tmp_path):
    _mk(tmp_path, [_rec(1), _rec(2, title="无关标题", tags=("x",), summary="无关")])
    _, rep = search.evaluate(tmp_path, query="nginx")
    assert rep["rejected"] == {"filter": 0, "query": 1}


def test_hit_fields_and_spans(tmp_path):
    _mk(tmp_path, [_rec(1, title="vite 指南", tags=("vite", "hmr"), summary="无关")])
    _, rep = search.evaluate(tmp_path, query="vite")
    m = rep["matched"][0]
    assert m["hit_fields"] == ["title", "tags"]
    assert m["rank"] == 1
    # hay = "vite 指南 vite hmr 无关"; tags 段起点 = len(title)+1
    start = len("vite 指南") + 1
    assert m["hit_spans"] == [[0, 4], [start, start + 4]]


def test_summary_only_hit(tmp_path):
    _mk(tmp_path, [_rec(1, title="t", tags=("a",), summary="提到了 zzz 一词")])
    _, rep = search.evaluate(tmp_path, query="zzz")
    assert rep["matched"][0]["hit_fields"] == ["summary"]


def test_no_query_all_pass_empty_fields(tmp_path):
    _mk(tmp_path, [_rec(1), _rec(2)])
    rows, rep = search.evaluate(tmp_path)
    assert rep["rejected"] == {"filter": 0, "query": 0}
    assert len(rep["matched"]) == 2
    assert all(m["hit_fields"] == [] and m["hit_spans"] == [] for m in rep["matched"])


def test_search_delegates_and_limit_unchanged(tmp_path):
    _mk(tmp_path, [_rec(i) for i in range(5)])
    limited = search.search(tmp_path, query="nginx", limit=2)
    rows, rep = search.evaluate(tmp_path, query="nginx")
    assert limited == rows[:2]
    assert len(rep["matched"]) == 5
    assert search.search(tmp_path, query="nope") == []


def test_case_insensitive(tmp_path):
    _mk(tmp_path, [_rec(1, title="Vite HMR Guide", tags=(), summary="")])
    _, rep = search.evaluate(tmp_path, query="VITE")
    assert rep["matched"][0]["hit_fields"] == ["title"]


def test_missing_index_returns_empty(tmp_path):
    rows, rep = search.evaluate(tmp_path)
    assert rows == [] and rep == {"scanned": 0,
                                  "rejected": {"filter": 0, "query": 0}, "matched": []}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_search_eval.py -q`
Expected: FAIL — `AttributeError: module 'kb.search' has no attribute 'evaluate'`

- [ ] **Step 3: 重写 search.py（evaluate + 委派）**

`src/kb/search.py` 整体替换为：

```python
from __future__ import annotations
import json
from pathlib import Path


def _load(repo_root: Path):
    jl = Path(repo_root) / "kb" / "index.jsonl"
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _parts(rec: dict) -> list[tuple[str, str]]:
    # 拼接顺序与既有 hay 逐字节一致: title → tags → summary(空格分隔, 小写)
    return [("title", str(rec.get("title", "")).lower()),
            ("tags", " ".join(rec.get("tags", [])).lower()),
            ("summary", str(rec.get("summary", "")).lower())]


def _hit(parts, q: str) -> tuple[list[str], list[list[int]]]:
    """q 在拼接文本中的全部出现位置 + 反解命中的字段名(顺序按字段首现)。"""
    hay, bounds = "", []
    for name, text in parts:
        hay = text if not hay else hay + " " + text
        bounds.append((name, len(hay) - len(text), len(hay)))
    fields: list[str] = []
    spans: list[list[int]] = []
    i = hay.find(q)
    while i >= 0:
        spans.append([i, i + len(q)])
        for name, s, e in bounds:
            if s <= i < e and name not in fields:
                fields.append(name)
        i = hay.find(q, i + 1)
    return fields, spans


def _filtered_out(rec, type, domain, tag, scope, status, confidence) -> bool:
    if type and rec["type"] != type:
        return True
    if domain and domain not in rec["domain"]:
        return True
    if tag and tag not in rec.get("tags", []):
        return True
    if scope and rec["scope"] != scope:
        return True
    if status and rec["status"] != status:
        return True
    if confidence and rec["confidence"] != confidence:
        return True
    return False


def evaluate(repo_root: Path, *, type=None, domain=None, tag=None, scope=None,
             status=None, confidence=None, query=None) -> tuple[list[dict], dict]:
    """全量评估(不截断): 返回 (命中行, 死因报告)。

    恒等式: rejected.filter + rejected.query + len(matched) == scanned。
    report 供 trace 埋点消费; rows 与改造前 search() 元素同形同序。
    """
    recs = _load(repo_root)
    q = query.lower() if query else None
    rows: list[dict] = []
    matched: list[dict] = []
    n_filter = n_query = 0
    for rec in recs:
        if _filtered_out(rec, type, domain, tag, scope, status, confidence):
            n_filter += 1
            continue
        fields, spans = ([], []) if q is None else _hit(_parts(rec), q)
        if q is not None and not fields:
            n_query += 1
            continue
        rows.append(rec)
        matched.append({"id": rec["id"], "title": rec.get("title"),
                        "scope": rec.get("scope"), "confidence": rec.get("confidence"),
                        "hit_fields": fields, "hit_spans": spans, "rank": len(matched) + 1})
    return rows, {"scanned": len(recs),
                  "rejected": {"filter": n_filter, "query": n_query},
                  "matched": matched}


def search(repo_root: Path, type=None, domain=None, tag=None, scope=None,
           status=None, confidence=None, query=None, limit: int = 20) -> list[dict]:
    rows, _ = evaluate(repo_root, type=type, domain=domain, tag=tag, scope=scope,
                       status=status, confidence=confidence, query=query)
    return rows[:limit]
```

- [ ] **Step 4: 跑新测试 + 既有检索回归**

Run: `python -m pytest tests/test_search_eval.py tests/test_search.py tests/test_index.py -q`
Expected: 全绿（`test_search.py` **未改动即通过** = 行为零漂移的证据）

- [ ] **Step 5: 全量 + 提交**

```powershell
python -m pytest -q
ruff check src tests
git add src/kb/search.py tests/test_search_eval.py
git commit -m "feat(search): evaluate 产出死因统计与 hit_fields/hit_spans, search 委派不改行为"
```

---

### Task 3: 双层死因报告 + 事件组装纯函数

**Files:**
- Modify: `src/kb/layers.py`
- Modify: `src/kb/trace.py`（追加两个组装函数）
- Create: `tests/test_trace_layers.py`

**Interfaces:**
- Consumes: `search.evaluate`（Task 2）、`trace` 写入（Task 1）
- Produces:
  - `layers.search_layers_report(repos, *, type=None, domain=None, tag=None, scope=None, status=None, confidence=None, query=None, limit=10) -> tuple[list[dict], list[dict]]`
    - 每个 report 在 Task 2 基础上补 `repo` / `taken` / `truncated_at_limit`
  - `layers.search_layers(...)` 签名与返回**不变**
  - `trace.build_search_event(*, trace_id, source, caller_repo, query, filters, limit, reports, returned, duration_ms, ts=None) -> dict`
  - `trace.build_get_event(*, trace_id, source, caller_repo, id, layer, ok, ts=None) -> dict`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_trace_layers.py`：

```python
import json
import pytest
from kb import layers, search, trace


def _mk(root, name, recs):
    d = root / name / "kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return root / name


def _rec(i, title, scope="project", **over):
    r = {"id": f"kb-{i}", "title": title, "type": "pitfall", "domain": ["frontend"],
         "tags": [], "scope": scope, "status": "accepted", "confidence": "verified",
         "summary": "s", "path": "kb/pitfall/frontend/x.md", "updated": "2026-10-12",
         "repo": "web"}
    r.update(over)
    return r


def test_report_shape_and_truncation(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(i, f"vite {i}") for i in range(3)])
    kb = _mk(tmp_path, "kb", [_rec(i, f"vite k{i}", scope="stack") for i in range(4)])
    rows, reports = layers.search_layers_report([docs, kb], query="vite", limit=4)
    assert len(rows) == 4
    assert [r["repo"] for r in reports] == ["docs", "kb"]
    assert reports[0]["taken"] == 3 and reports[0]["truncated_at_limit"] is False
    assert reports[1]["taken"] == 1 and reports[1]["truncated_at_limit"] is True
    assert reports[1]["scanned"] == 4
    assert reports[1]["rejected"] == {"filter": 0, "query": 0}
    assert [m["rank"] for m in reports[1]["matched"]] == [1, 2, 3, 4]


def test_search_layers_still_equal_layerwise_concat(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(i, f"vite {i}") for i in range(3)])
    kb = _mk(tmp_path, "kb", [_rec(i, f"vite k{i}", scope="stack") for i in range(4)])
    a = layers.search_layers([docs, kb], query="vite", limit=4)
    b = search.search(docs, query="vite", limit=4) + search.search(kb, query="vite", limit=4)
    assert a == b[:4]


def test_single_layer_zero_matches(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(1, "a", type="howto"), _rec(2, "b")])
    rows, reports = layers.search_layers_report([docs], query="vite", type="pitfall")
    rep = reports[0]
    assert rep["scanned"] == 2
    assert rep["rejected"] == {"filter": 1, "query": 1}
    assert rep["matched"] == [] and rows == [] and rep["taken"] == 0


def test_build_search_event_shape(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(1, "vite x")])
    _, rep = search.evaluate(docs, query="vite")
    rep.update({"repo": "docs", "taken": 1, "truncated_at_limit": False})
    ev = trace.build_search_event(
        trace_id="t-1", source="mcp", caller_repo="flysee_video_web", query="vite",
        filters={"type": "pitfall", "domain": None, "tag": None, "scope": None,
                 "status": None, "confidence": None},
        limit=10, reports=[rep], returned=["kb-1"], duration_ms=7)
    assert ev["kind"] == "search" and ev["trace_id"] == "t-1"
    assert ev["source"] == "mcp" and ev["caller_repo"] == "flysee_video_web"
    assert ev["returned"] == ["kb-1"] and ev["duration_ms"] == 7
    assert set(ev["filters"]) == {"type", "domain", "tag", "scope", "status", "confidence"}
    assert len(ev["layers"]) == 1
    assert set(ev["layers"][0]) == {"repo", "scanned", "rejected", "matched",
                                    "taken", "truncated_at_limit"}
    assert ev["layers"][0]["matched"][0]["hit_fields"] == ["title"]
    assert ev["ts"][:4].isdigit()


def test_build_get_event():
    ev = trace.build_get_event(trace_id="t-1", source="mcp", caller_repo="web",
                               id="kb-1", layer="docs", ok=True)
    assert ev["kind"] == "get" and ev["id"] == "kb-1"
    assert ev["layer"] == "docs" and ev["ok"] is True and ev["trace_id"] == "t-1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trace_layers.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'search_layers_report'`

- [ ] **Step 3: layers 加报告版**

`src/kb/layers.py`：import 行 `from kb.search import search` 改为 `from kb.search import evaluate`；`search_layers` 整体替换为下面两段：

```python
def search_layers_report(repos: list[Path], *, type=None, domain=None, tag=None,
                         scope=None, status=None, confidence=None, query=None,
                         limit: int = 10) -> tuple[list[dict], list[dict]]:
    """双层合并检索 + 逐层死因报告(供 trace)。repos 顺序即优先级, 逐层取满即截断。"""
    out: list[dict] = []
    reports: list[dict] = []
    for rp in repos:
        rows, rep = evaluate(rp, type=type, domain=domain, tag=tag, scope=scope,
                             status=status, confidence=confidence, query=query)
        take = max(0, limit - len(out))
        chosen = rows[:take]
        rep.update({"repo": _name(rp), "taken": len(chosen),
                    "truncated_at_limit": len(chosen) < len(rows)})
        reports.append(rep)
        out.extend(chosen)
    return out[:limit], reports


def search_layers(repos: list[Path], *, type=None, domain=None, tag=None, scope=None,
                  status=None, confidence=None, query=None, limit: int = 10) -> list[dict]:
    """双层合并检索: repos 顺序即优先级, 逐层取满即截断(spec §7)。"""
    rows, _ = search_layers_report(repos, type=type, domain=domain, tag=tag, scope=scope,
                                   status=status, confidence=confidence, query=query,
                                   limit=limit)
    return rows
```

- [ ] **Step 4: trace 加事件组装**

追加到 `src/kb/trace.py`：

```python
def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def build_search_event(*, trace_id: str, source: str, caller_repo: str,
                       query: str | None, filters: dict, limit: int,
                       reports: list[dict], returned: list[str],
                       duration_ms: int, ts: str | None = None) -> dict:
    """逐层报告 → search 事件(字段序即 spec §4.4 schema)。只取元数据, 不带正文。"""
    return {
        "kind": "search", "trace_id": trace_id, "ts": ts or _now(), "source": source,
        "caller_repo": caller_repo, "query": query,
        "filters": {k: filters.get(k) for k in
                    ("type", "domain", "tag", "scope", "status", "confidence")},
        "limit": limit, "duration_ms": duration_ms,
        "layers": [{"repo": r["repo"], "scanned": r["scanned"],
                    "rejected": r["rejected"], "matched": r["matched"],
                    "taken": r["taken"], "truncated_at_limit": r["truncated_at_limit"]}
                   for r in reports],
        "returned": list(returned),
    }


def build_get_event(*, trace_id: str | None, source: str, caller_repo: str, id: str,
                    layer: str | None, ok: bool, ts: str | None = None) -> dict:
    return {"kind": "get", "trace_id": trace_id, "ts": ts or _now(), "source": source,
            "caller_repo": caller_repo, "id": id, "layer": layer, "ok": ok}
```

- [ ] **Step 5: 全量 + 提交**

```powershell
python -m pytest -q
ruff check src tests
git add src/kb/layers.py src/kb/trace.py tests/test_trace_layers.py
git commit -m "feat(trace): 双层死因报告与 search/get 事件组装纯函数"
```

---

### Task 4: CLI `kb search` 埋点接线

**Files:**
- Modify: `src/kb/cli.py`（`p_s` 参数定义处 + `if args.cmd == "search":` 分支）
- Create: `tests/test_trace_cli.py`

**Interfaces:**
- Consumes: `trace.trace_enabled/build_search_event/new_trace_id/append_event`（Task 1/3）、`layers.search_layers_report`（Task 3）
- Produces: `kb search ... [--trace | --no-trace]`；事件 `source="cli"`，`caller_repo = repo.resolve().name.lower()`；stdout 输出与改造前逐字节一致

- [ ] **Step 1: 写失败测试**

创建 `tests/test_trace_cli.py`（沿用 `conftest.make_entry` 建条目 + `kb index` 生成索引，与 `test_cli.py` 同套路）：

```python
import json
import pytest
from kb import trace
from kb.cli import main
from conftest import make_entry


@pytest.fixture
def env(tmp_path, monkeypatch):
    """业务仓 Flysee_Web(含索引) + Agent-KB 根指向 tmp, 隔离真实 traces/。"""
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    monkeypatch.delenv("KB_TRACE", raising=False)
    proj = tmp_path / "Flysee_Web"
    d = proj / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261012-aaaa", title="Vite HMR 失效",
                                       status="accepted", confidence="verified"),
                            encoding="utf-8")
    (d / "b.md").write_text(make_entry(id="kb-20261012-bbbb", title="无关标题",
                                       tags=["nginx"], status="accepted",
                                       confidence="verified"), encoding="utf-8")
    main(["index", "--repo", str(proj)])
    return root, proj


def _events(root):
    out = []
    for f in sorted((root / "traces").glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            if e.get("kind") != "meta":
                out.append(e)
    return out


def test_off_writes_nothing(env, capsys):
    root, proj = env
    assert main(["search", "--repo", str(proj), "--query", "vite"]) == 0
    assert not (root / "traces").exists()
    assert "kb-20261012-aaaa" in capsys.readouterr().out


def test_flag_on_writes_event(env, capsys):
    root, proj = env
    assert main(["search", "--repo", str(proj), "--query", "vite", "--trace"]) == 0
    out = json.loads(capsys.readouterr().out)   # stdout 仍是纯 JSON 结果
    assert [r["id"] for r in out] == ["kb-20261012-aaaa"]
    evs = _events(root)
    assert len(evs) == 1 and evs[0]["source"] == "cli"
    assert evs[0]["caller_repo"] == "flysee_web"          # resolve().name.lower()
    assert evs[0]["returned"] == ["kb-20261012-aaaa"]
    lay = evs[0]["layers"][0]
    assert lay["scanned"] == 2
    assert lay["rejected"] == {"filter": 0, "query": 1}
    assert lay["matched"][0]["hit_fields"] == ["title"]


def test_no_trace_beats_env(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    assert main(["search", "--repo", str(proj), "--query", "vite", "--no-trace"]) == 0
    assert not (root / "traces").exists()


def test_env_on_and_marker(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    main(["search", "--repo", str(proj), "--query", "vite"])
    assert len(_events(root)) == 1


def test_flag_and_no_flag_reject_each_other(env):
    _, proj = env
    with pytest.raises(SystemExit):
        main(["search", "--repo", str(proj), "--trace", "--no-trace"])


def test_event_has_no_body(env):
    root, proj = env
    main(["search", "--repo", str(proj), "--query", "vite", "--trace"])
    dump = json.dumps(_events(root), ensure_ascii=False)
    assert "根因" not in dump and "背景" not in dump   # make_entry 正文段名
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trace_cli.py -q`
Expected: FAIL — `unrecognized arguments: --trace`（argparse SystemExit）

- [ ] **Step 3: 实现 CLI 接线**

`src/kb/cli.py` 顶部 import 区追加：

```python
import time
from kb import trace as kbtrace
from kb.layers import search_layers_report
```

`p_s` 定义中 `p_s.add_argument("--limit", type=int, default=20)` 之后追加：

```python
    g = p_s.add_mutually_exclusive_group()
    g.add_argument("--trace", dest="trace_on", action="store_true", default=None,
                   help="本次强制记录检索 trace")
    g.add_argument("--no-trace", dest="trace_on", action="store_false",
                   help="本次强制不记录检索 trace")
```

注意：互斥组两条必须用**同一 `dest`**（`trace_on`）且默认 `None`，这样三态（开/关/未指定）与互斥校验同时成立。

`if args.cmd == "search":` 分支整体替换为：

```python
    if args.cmd == "search":
        t0 = time.perf_counter()
        layers_list = [repo] + [Path(p) for p in args.agent_kb]
        res, reports = search_layers_report(
            layers_list, type=args.type, domain=args.domain, tag=args.tag,
            scope=args.scope, status=args.status, confidence=args.confidence,
            query=args.query, limit=args.limit)
        if kbtrace.trace_enabled(cli_flag=args.trace_on):
            ev = kbtrace.build_search_event(
                trace_id=kbtrace.new_trace_id(), source="cli",
                caller_repo=repo.resolve().name.lower(), query=args.query,
                filters={"type": args.type, "domain": args.domain, "tag": args.tag,
                         "scope": args.scope, "status": args.status,
                         "confidence": args.confidence},
                limit=args.limit, reports=reports,
                returned=[r["id"] for r in res],
                duration_ms=round((time.perf_counter() - t0) * 1000))
            kbtrace.append_event(ev)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
```

（原分支的 `if args.agent_kb: search_layers(...) else: search(...)` 二选一删除 — `search_layers_report` 对单层等价。顶部 import 行 `from kb.layers import search_layers, get_layered, related_layers` 改为 `from kb.layers import get_layered, related_layers`（`search_layers` 在 cli.py 已无使用，留着会 F401）。）

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_trace_cli.py tests/test_cli.py tests/test_search.py -q`
Expected: 全绿（`test_cli.py` 未改动即通过 = 输出零漂移证据）

- [ ] **Step 5: 全量 + 提交**

```powershell
python -m pytest -q
ruff check src tests
git add src/kb/cli.py tests/test_trace_cli.py
git commit -m "feat(trace): kb search --trace/--no-trace 埋点接线(默认关闭)"
```

---

### Task 5: MCP `kb_search` / `kb_get` 埋点 + `kb.mcp --trace`

**Files:**
- Modify: `src/kb/mcp_server.py`
- Modify: `src/kb/mcp.py`
- Create: `tests/test_trace_mcp.py`

**Interfaces:**
- Consumes: Task 3/4 全部接口；`build_server(repo, agent_kbs, repo_name)` 既有闭包变量 `name` / `layers`
- Produces: MCP `kb_search` → `source="mcp"` 事件；`kb_get` → get 事件且 `trace_id` 关联同 caller 最近 search；`python -m kb.mcp --trace` 等价 `KB_TRACE=1`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_trace_mcp.py`（复用 `test_mcp.py` 的连接方式）：

```python
import json
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from kb import trace
from kb.index import build_indexes
from kb.mcp_server import build_server
from conftest import make_entry

pytestmark = pytest.mark.asyncio


async def _call(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool(name, args)
        return res.isError, res.content[0].text


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    monkeypatch.delenv("KB_TRACE", raising=False)
    proj = tmp_path / "docs"
    d = proj / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261012-aaaa", title="Vite HMR 抖动",
                                       status="accepted", confidence="verified")
                            + "\n## 根因\n项目层机制说明文本。\n", encoding="utf-8")
    build_indexes(proj, repo_name="docs")
    return root, proj


def _events(root):
    out = []
    for f in sorted((root / "traces").glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            if e.get("kind") != "meta":
                out.append(e)
    return out


async def test_mcp_off_writes_nothing(env):
    root, proj = env
    srv = build_server(proj, [proj], repo_name="docs")
    err, _ = await _call(srv, "kb_search", {"query": "Vite"})
    assert err is False
    assert not (root / "traces").exists()


async def test_search_event_written(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [proj], repo_name="docs")
    err, text = await _call(srv, "kb_search", {"query": "Vite"})
    assert err is False and json.loads(text)[0]["id"] == "kb-20261012-aaaa"
    evs = _events(root)
    assert len(evs) == 1 and evs[0]["source"] == "mcp"
    assert evs[0]["caller_repo"] == "docs"
    assert evs[0]["returned"] == ["kb-20261012-aaaa"]
    assert evs[0]["layers"][0]["matched"][0]["hit_fields"] == ["title"]


async def test_get_links_to_recent_search(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [proj], repo_name="docs")
    await _call(srv, "kb_search", {"query": "Vite"})
    sid = _events(root)[0]["trace_id"]
    await _call(srv, "kb_get", {"id": "kb-20261012-aaaa"})
    get_ev = _events(root)[1]
    assert get_ev["kind"] == "get" and get_ev["id"] == "kb-20261012-aaaa"
    assert get_ev["trace_id"] == sid and get_ev["layer"] == "docs" and get_ev["ok"] is True


async def test_get_miss_records_ok_false(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [proj], repo_name="docs")
    err, _ = await _call(srv, "kb_get", {"id": "kb-00000000-0000"})
    assert err is True                      # 工具仍报错
    ev = _events(root)[-1]
    assert ev["kind"] == "get" and ev["ok"] is False and ev["layer"] is None


def test_mcp_cli_trace_flag_sets_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KB_TRACE", raising=False)
    from kb import mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "build_server",
                        lambda *a, **k: type("S", (), {"run": lambda self, **kw: None})())
    assert mcp_mod.main(["--repo", str(tmp_path), "--trace"]) == 0
    import os
    assert os.environ.get("KB_TRACE") == "1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trace_mcp.py -q`
Expected: FAIL — traces 目录不存在 / `--trace` 不识别

- [ ] **Step 3: mcp_server 埋点**

`src/kb/mcp_server.py` import 区改为：

```python
import time
from kb import trace as kbtrace
from kb.layers import get_layered, related_layers, search_layers_report
```

（删除原 `search_layers` import；`kb_search` 是唯一使用者。）`kb_search` / `kb_get` 两个工具函数整体替换为：

```python
    @mcp.tool()
    def kb_search(query: str | None = None, type: str | None = None,
                  domain: str | None = None, tag: str | None = None,
                  scope: str | None = None, limit: int = 10) -> str:
        """检索知识库(项目层优先, 再通用层)。只返回元数据+摘要, 不返回正文。
        draft 条目永不返回。命中后再用 kb_get 读全文。"""
        t0 = time.perf_counter()
        rows, reports = search_layers_report(
            layers, type=type, domain=domain, tag=tag, scope=scope, query=query, limit=limit)
        if kbtrace.trace_enabled():
            kbtrace.append_event(kbtrace.build_search_event(
                trace_id=kbtrace.new_trace_id(), source="mcp", caller_repo=name,
                query=query, filters={"type": type, "domain": domain, "tag": tag,
                                      "scope": scope, "status": None, "confidence": None},
                limit=limit, reports=reports, returned=[r["id"] for r in rows],
                duration_ms=round((time.perf_counter() - t0) * 1000)))
        keep = ("id", "title", "type", "domain", "tags", "scope", "status",
                "severity", "confidence", "path", "summary", "updated", "repo")
        return _json([{k: r.get(k) for k in keep} for r in rows])

    @mcp.tool()
    def kb_get(id: str) -> str:
        """按 id 读取单条全文 markdown。"""
        got = get_layered(layers, id)
        if kbtrace.trace_enabled():
            kbtrace.append_event(kbtrace.build_get_event(
                trace_id=kbtrace.latest_search_id(name), source="mcp", caller_repo=name,
                id=id, layer=got[1] if got else None, ok=got is not None))
        if got is None:
            raise ValueError(f"not found: {id}")
        return got[0]
```

- [ ] **Step 4: `kb.mcp --trace`**

`src/kb/mcp.py` 的 `main` 中 `ap.add_argument("--repo-name", ...)` 之后追加参数，`a = ap.parse_args(argv)` 之后插入两行：

```python
    ap.add_argument("--trace", action="store_true", help="等价 KB_TRACE=1, 记录检索 trace")
```

```python
    if a.trace:
        import os
        os.environ["KB_TRACE"] = "1"
```

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_trace_mcp.py tests/test_mcp.py -q`
Expected: 全绿（`test_mcp.py` 未改动即通过 = MCP 返回值零漂移）

- [ ] **Step 6: 全量 + 提交**

```powershell
python -m pytest -q
ruff check src tests
git add src/kb/mcp_server.py src/kb/mcp.py tests/test_trace_mcp.py
git commit -m "feat(trace): MCP kb_search/kb_get 埋点与 kb.mcp --trace 开关"
```

---

### Task 6: `kb trace list / show` 子命令

**Files:**
- Modify: `src/kb/cli.py`
- Create: `tests/test_trace_command.py`

**Interfaces:**
- Consumes: `trace.read_traces/find_trace`（Task 1）
- Produces: `kb trace list [--caller X] [--since YYYY-MM-DD] [--zero-hit] [--limit N]`（表格 + warnings 到 stderr，空目录打印开启指引、rc=0）；`kb trace show <id>`（完整 JSON，未知 id rc=1）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_trace_command.py`：

```python
import json
import pytest
from kb import trace
from kb.cli import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    return root


def _seed(root):
    for i, caller in enumerate(["web", "algo"]):
        trace.append_event({"kind": "search", "trace_id": f"t-1{i}", "ts": f"2026-10-1{i + 4}T10:00:00+08:00",
                            "source": "cli", "caller_repo": caller, "query": f"q{i}",
                            "filters": {}, "limit": 10, "duration_ms": 2,
                            "layers": [], "returned": ["kb-1"] if i == 0 else []}, root=root)


def test_list_empty_guidance(env, capsys):
    assert main(["trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "KB_TRACE" in out           # 引导语指向开关


def test_list_table_and_filters(env, capsys):
    _seed(env)
    assert main(["trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "t-11" in out and "t-10" in out and "0命中" in out
    assert main(["trace", "list", "--caller", "web"]) == 0
    out = capsys.readouterr().out
    assert "t-10" in out and "t-11" not in out
    assert main(["trace", "list", "--since", "2026-10-15"]) == 0
    out = capsys.readouterr().out
    assert "t-11" in out and "t-10" not in out   # seed ts: t-10=10-14, t-11=10-15


def test_show_found_and_missing(env, capsys):
    _seed(env)
    assert main(["trace", "show", "t-10"]) == 0
    assert json.loads(capsys.readouterr().out)["trace_id"] == "t-10"
    assert main(["trace", "show", "nope"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trace_command.py -q`
Expected: FAIL — `invalid choice: 'trace'`

- [ ] **Step 3: 实现子命令**

`src/kb/cli.py`：`p_ex = sub.add_parser("export", ...)` 块之后追加解析器：

```python
    p_tr = sub.add_parser("trace", parents=[common])
    tr_sub = p_tr.add_subparsers(dest="trace_cmd", required=True)
    p_tl = tr_sub.add_parser("list")
    p_tl.add_argument("--caller", default=None)
    p_tl.add_argument("--since", default=None, help="YYYY-MM-DD")
    p_tl.add_argument("--zero-hit", action="store_true")
    p_tl.add_argument("--limit", type=int, default=30)
    p_ts = tr_sub.add_parser("show")
    p_ts.add_argument("id")
```

`if args.cmd == "promote":` 分支之前插入处理分支：

```python
    if args.cmd == "trace":
        from kb import trace as kbtrace
        if args.trace_cmd == "show":
            ev = kbtrace.find_trace(args.id)
            if ev is None:
                print(f"trace not found: {args.id}", file=sys.stderr)
                return 1
            print(json.dumps(ev, ensure_ascii=False, indent=2))
            return 0
        searches, _, warns = kbtrace.read_traces(caller=args.caller, since=args.since,
                                                 zero_hit=args.zero_hit, limit=args.limit)
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        if not searches:
            print("暂无 trace 记录。开启方式: kb search --trace / 环境变量 KB_TRACE=1 / "
                  "仓根放置 .kb-trace 标记文件")
            return 0
        print(f"{'时间':<20} {'来源':<5} {'caller':<22} {'命中':>4}  query / trace_id")
        for s in searches:
            hits = len(s.get("returned", []))
            flag = " 0命中" if hits == 0 else f" {hits:>4}"
            print(f"{str(s.get('ts', ''))[:19]:<20} {s.get('source', ''):<5} "
                  f"{s.get('caller_repo', ''):<22}{flag}  "
                  f"{s.get('query') or '-'} / {s.get('trace_id')}")
        return 0
```

- [ ] **Step 4: 跑测试 + 全量 + 提交**

```powershell
python -m pytest tests/test_trace_command.py -q
python -m pytest -q
ruff check src tests
git add src/kb/cli.py tests/test_trace_command.py
git commit -m "feat(trace): kb trace list/show 查看子命令"
```

---

### Task 7: spider 回放转换器（Phase 2）

**Files:**
- Create: `src/kb/spider_export.py`
- Modify: `src/kb/cli.py`（`kb trace export` 子命令）
- Create: `tests/test_spider_export.py`

**Interfaces:**
- Consumes: `trace.find_trace/read_traces`（Task 1）
- Produces: `spider_export.to_record(search_ev: dict, get_evs: list[dict]) -> dict` — 完整 `prompt-spider-session/v1` record 字典；CLI `kb trace export <id> -o out.json`

> **对端校准锚点**：record 顶层字段按对方文档 §4（`initialConfig` / `config` / 事件快照 / 有序 `log`，`revision` 递增、`at` 相对秒）。若导入真实 prompt-spider-ui 报错，只允许改 `spider_export.py` 顶部的 `RECORD_*` 常量区做字段名适配，不改 trace 数据层。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_spider_export.py`：

```python
import pytest
from kb import spider_export


def _trace():
    return {"kind": "search", "trace_id": "t-1", "ts": "2026-10-15T14:32:05+08:00",
            "source": "mcp", "caller_repo": "flysee_video_web", "query": "vite hmr",
            "filters": {"type": "pitfall", "domain": "frontend"}, "limit": 10,
            "duration_ms": 8,
            "layers": [
                {"repo": "docs", "scanned": 208, "rejected": {"filter": 150, "query": 40},
                 "matched": [{"id": "kb-a", "title": "vite hmr DOM 失效", "scope": "project",
                               "confidence": "verified", "hit_fields": ["title", "tags"],
                               "hit_spans": [[0, 4]], "rank": 1}],
                 "taken": 1, "truncated_at_limit": False},
                {"repo": "kb", "scanned": 195, "rejected": {"filter": 0, "query": 194},
                 "matched": [{"id": "kb-b", "title": "keep-alive SSE", "scope": "stack",
                               "confidence": "probable", "hit_fields": ["summary"],
                               "hit_spans": [[10, 14]], "rank": 1}],
                 "taken": 1, "truncated_at_limit": False}],
            "returned": ["kb-a", "kb-b"]}


def _gets():
    return [{"kind": "get", "trace_id": "t-1", "ts": "2026-10-15T14:33:00+08:00",
             "source": "mcp", "caller_repo": "flysee_video_web", "id": "kb-a",
             "layer": "docs", "ok": True},
            {"kind": "get", "trace_id": "t-9", "ts": "2026-10-15T15:00:00+08:00",
             "source": "mcp", "caller_repo": "flysee_video_web", "id": "kb-z",
             "layer": "docs", "ok": True}]


def test_record_shape():
    rec = spider_export.to_record(_trace(), _gets())
    assert rec["format"] == "prompt-spider-session/v1"
    assert rec["config"]["title"].startswith("KB 命中")
    assert rec["config"]["unit"] == "task"
    labels = {r["label"] for r in rec["config"]["routes"].values()}
    assert labels == {"项目层命中", "通用层命中", "已读消费"}


def test_events_and_routes():
    rec = spider_export.to_record(_trace(), _gets())
    by_id = {e["id"]: e for e in rec["events"]}
    assert set(by_id) == {"kb-a", "kb-b"}
    assert by_id["kb-a"]["route"] == "you"          # 被 kb_get 消费 → 已读分支
    assert by_id["kb-b"]["route"] == "model"        # 通用层命中
    assert "hit: title+tags" in by_id["kb-a"]["detail"]
    assert by_id["kb-b"]["detail"].startswith("hit: summary")


def test_log_monotonic_and_revision_ordered():
    rec = spider_export.to_record(_trace(), _gets())
    log = rec["log"]
    assert [e["revision"] for e in log] == list(range(1, len(log) + 1))
    assert all(b["at"] >= a["at"] for a, b in zip(log, log[1:]))
    assert log[0]["at"] >= 0


def test_zero_hit_trace_valid():
    tr = _trace()
    tr["layers"] = [{**tr["layers"][0], "matched": [], "taken": 0}]
    tr["returned"] = []
    rec = spider_export.to_record(tr, [])
    assert rec["events"] == []
    assert "0 命中" in rec["config"]["subtitle"]


def test_unrelated_get_ignored():
    rec = spider_export.to_record(_trace(), _gets())   # kb-z/t-9 不在本 trace
    assert {e["id"] for e in rec["events"]} == {"kb-a", "kb-b"}
    assert rec["events"][0]["status"] == "completed"


def test_deterministic():
    a = spider_export.to_record(_trace(), _gets())
    b = spider_export.to_record(_trace(), _gets())
    assert a == b
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_spider_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kb.spider_export'`

- [ ] **Step 3: 实现转换器**

创建 `src/kb/spider_export.py`：

```python
from __future__ import annotations
"""trace → prompt-spider-session/v1 转换器(spec §6)。

纯函数: 只消费 trace dict, 不碰文件。有损映射(扫描线/字段高亮降级为 detail 文字)。
导入报错时只改本文件 RECORD_* 常量区适配, 不动数据层。
"""

FORMAT = "prompt-spider-session/v1"
ROUTES = {"code": {"label": "项目层命中", "color": "#42D6A4"},
          "model": {"label": "通用层命中", "color": "#F28A76"},
          "you": {"label": "已读消费", "color": "#F0CA57"}}
_LAYER_ROUTE = {0: "code", 1: "model"}   # reports 顺序: 项目层在前(spec §7)


def _detail(m: dict) -> str:
    fields = "+".join(m["hit_fields"]) or "filter"
    return f"hit: {fields} @ {m['hit_spans']}"


def to_record(search_ev: dict, get_evs: list[dict]) -> dict:
    """一条 search trace + 其关联 get 事件 → 可导入的完整 record。"""
    read_ids = {g["id"] for g in get_evs if g.get("trace_id") == search_ev["trace_id"]}
    ts = str(search_ev.get("ts", ""))[:10]
    returned = set(search_ev.get("returned", []))
    events: list[dict] = []
    for idx, layer in enumerate(search_ev.get("layers", [])):
        route = _LAYER_ROUTE.get(idx, "model")
        for m in layer["matched"]:
            if m["id"] not in returned:
                continue
            final = "you" if m["id"] in read_ids else route
            events.append({"id": m["id"], "label": m["title"][:40] or m["id"],
                           "route": final, "status": "completed",
                           "detail": _detail(m)})
    consumed = {e["id"] for e in events if e["route"] == "you"}
    events.sort(key=lambda e: (e["route"] != "code", e["route"] != "model", e["id"]))
    layers_note = " · ".join(
        f"{l['repo']} 扫描{l['scanned']} 过滤-{l['rejected']['filter']} 词-{l['rejected']['query']}"
        for l in search_ev.get("layers", []))
    n = len(events)
    config = {
        "title": f"KB 命中回放 {search_ev['trace_id']}",
        "subtitle": (f"query: {search_ev.get('query') or '-'} | {layers_note} | "
                     f"limit={search_ev.get('limit')}"
                     + (" | 0 命中" if n == 0 else "")),
        "modelName": f"{search_ev.get('caller_repo', '?')} · {ts}",
        "layout": "landscape", "unit": "task", "routes": ROUTES,
    }
    log = [{"revision": 1, "at": 0.0, "kind": "config", "config": config}]
    if events:
        log.append({"revision": 2, "at": 0.5, "kind": "events",
                    "events": [dict(e, status="running") for e in events
                               if e["route"] != "you"]})
        log.append({"revision": 3, "at": 1.5, "kind": "events",
                    "events": [dict(e, status="completed") for e in events]})
    log.append({"revision": len(log) + 1, "at": 2.5, "kind": "complete",
                "status": "completed"})
    return {"format": FORMAT, "initialConfig": config, "config": config,
            "events": events, "log": log,
            "consumed": sorted(consumed)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_spider_export.py -q`
Expected: `6 passed`

- [ ] **Step 5: CLI `kb trace export`**

`src/kb/cli.py` trace 解析器区（Task 6 的 `p_ts` 之后）追加：

```python
    p_te = tr_sub.add_parser("export")
    p_te.add_argument("id")
    p_te.add_argument("--format", default="spider", choices=["spider"])
    p_te.add_argument("-o", "--out", default=None, help="输出文件, 默认 <trace_id>.json")
```

trace 处理分支内 `show` 之前插入：

```python
        if args.trace_cmd == "export":
            from kb.spider_export import to_record
            ev = kbtrace.find_trace(args.id)
            if ev is None:
                print(f"trace not found: {args.id}", file=sys.stderr)
                return 1
            _, gets, _ = kbtrace.read_traces()
            rec = to_record(ev, [g for g in gets
                                 if g.get("trace_id") == args.id])
            out = Path(args.out) if args.out else Path(f"{args.id}.json")
            out.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(out)
            return 0
```

- [ ] **Step 6: 补 CLI 级测试**

追加到 `tests/test_spider_export.py`：

```python
def test_cli_export(env, tmp_path, capsys):
    from kb.cli import main
    from kb import trace as tr
    tr.append_event(_trace(), root=env)
    for g in _gets():
        tr.append_event(g, root=env)
    out = tmp_path / "rec.json"
    assert main(["trace", "export", "t-1", "-o", str(out)]) == 0
    import json
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["format"] == "prompt-spider-session/v1"


import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr("kb.trace.kb_root", lambda: root)
    return root
```

- [ ] **Step 7: 全量 + 提交**

```powershell
python -m pytest -q
ruff check src tests
git add src/kb/spider_export.py src/kb/cli.py tests/test_spider_export.py
git commit -m "feat(trace): kb trace export 转换器, 产出 prompt-spider-session/v1 回放"
```

- [ ] **Step 8: 端到端人工验收（唯一需要人的一步）**

```powershell
# 1. 开埋点跑一次真实检索
$env:KB_TRACE = "1"
kb search --query "vite hmr" --repo . ; kb search --query "sse" --repo .
# 2. 查看
kb trace list ; kb trace show <列表里的 id>
# 3. 导出
kb trace export <id> -o demo.json
# 4. 克隆并导入观看(需 Node 20+)
git clone https://github.com/Kirito14IT/prompt-spider-ui ; cd prompt-spider-ui ; npm --prefix mcp ci
#    在任意 MCP 客户端里调 spider_import_session({"record": <demo.json 内容>}) 或浏览器导入
```

验收标准（spec §8）：回放可见 query 词条、三层分流（项目层/通用层/已读）、detail 含命中字段；导入若报字段名错误 → 只改 `spider_export.py` 常量区后重试。

---

## 规格覆盖自检（Plan 作者已完成）

| spec 条目 | 实现任务 |
| --- | --- |
| §4.1 开关优先级 | Task 1（8 条开关测试） |
| §4.2 落盘/红线/静默降级 | Task 1（meta 一次、OSError 吞）+ Task 4（无正文断言） |
| §4.3 一处埋点两入口 / get 事件 | Task 3（纯函数）+ Task 4（CLI）+ Task 5（MCP） |
| §4.4 schema 与死因恒等式 | Task 2（恒等式测试）+ Task 3（shape 测试） |
| §5 `kb trace list/show` | Task 6 |
| §6 转换器与映射表 | Task 7 |
| §7 错误处理四场景 | Task 1（reader）+ Task 6（show 未知 id） |
| §8 验收 | Task 7 Step 8 |
| Global: 默认关闭零影响 | Task 4/5 的 off 用例 + `test_cli.py`/`test_mcp.py` 原样通过 |

