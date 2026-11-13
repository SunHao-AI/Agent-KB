# 检索部分命中降级(AND-first + Partial Fallback)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 严格 AND 零结果且 tokens≥2 时降级为部分命中(≥min(2,去重token数)), 让描述式长查询不再全 AND 硬拒, 同时保证 AND 有结果时行为逐字节不变。

**Architecture:** 只改 `src/kb/search.py` 的匹配策略单点(`_hit` 三态化 + `evaluate` 二遍降级分支), 报告加 `match_mode`/`partial` 可选键; trace 事件在 `build_search_event` 白名单处显式透传 `match_mode`; 新增离线回放脚本用 traces 历史 query 对当前索引做新旧策略对比验收。索引、MCP/CLI 签名、聚合口径、面板全部不动。

**Tech Stack:** Python 3(标准库 only)、pytest、本仓 `kb` CLI(`kb lint` / `kb index --check`)。

**Spec:** `docs/superpowers/specs/2026-11-13-search-partial-hit-design.md`(commit 4095b17)

## Global Constraints

- 严格 AND 有任何结果 → 结果集与排序**逐字节不变**; 单 token 查询永不降级。
- 降级门槛: `len(hit_tokens) >= min(2, len(set(tokens)))`; 排序键 `(-round(len(hit_tokens)/len(set(tokens)), 6), -score, index)`, score 复用 `_score(rec, fields, spans, hit_tokens, today)`。
- 恒等式保持: `rejected.filter + rejected.query + len(matched) == scanned`; 降级后仍零命中的条目(含低于门槛的)计入 `rejected.query`。
- `report["match_mode"] = "and" | "partial"` 仅在**有 query** 时写; partial 时加 `report["partial"] = {"min_hit": k, "tokens": n}`; 无 query 时 report 键集与现在完全一致(兼容红线: `test_missing_index_returns_empty` 用 `rep ==` 精确相等)。
- trace search 事件 `layers` 元素加 `match_mode`(取 `r.get("match_mode")`, limit≤0 短路与旧数据无此键时为 None); hit_rate/consume_rate 聚合口径不变; 面板不改。
- 不动索引构建(index.jsonl 字段)、不改 MCP/CLI 参数签名与返回结构(除新增可选键)、不引入分词器、不调 `_CJK_COVERAGE`。
- 环境: Windows PowerShell 5, **不支持 `&&`, 顺序命令用 `;`**; 测试命令 `python -m pytest`; 本仓 kb 命令一律带 `--repo .`; `traces/` 目录不得纳入功能提交。
- 代码注释一律中文, 与仓内现有风格一致(解释"为什么"而非"是什么")。

---

### Task 1: `_hit` 三态化(全/部分/零命中)

**Files:**
- Modify: `src/kb/search.py:68-91`(`_hit`) 与 `src/kb/search.py:162-165`(`evaluate` 主循环调用点, 本任务仅做行为不变的适配解包)
- Modify: `scripts/noise-gate.py:65`(`_hit` 第二个调用点, 二元解包必须同步改, 否则该脚本 TypeError)
- Test: `tests/test_search_eval.py`(文件末尾追加)

**Interfaces:**
- Consumes: `_token_spans(hay, tok) -> list[list[int]]`(不动); `_parts(rec) -> list[tuple[str, str]]`(不动)。
- Produces: `_hit(parts, tokens) -> tuple[list[str], list[list[int]], set[str]]` —— 第三元素 `hit_tokens` 为已命中 token 集合; 全命中 `hit_tokens == set(tokens)`; 零命中 `([], [], set())`; 部分命中返回已命中 token 的 fields/spans。Task 2 依赖该三元组。

- [ ] **Step 1: 写失败测试(三态返回)**

在 `tests/test_search_eval.py` 末尾追加(文件顶部已有 `import json` / `from kb import search`, 无需新 import; `_rec` 夹具已存在):

```python
# ---- 部分命中降级 spec 3.1: _hit 三态 ----

def test_hit_returns_triple_with_hit_tokens():
    from kb.search import _hit, _parts

    parts = _parts(_rec(1, title="vite hmr 抖动", tags=("vite",), summary=""))
    # 全命中: hit_tokens 覆盖全部 token, fields/spans 与旧行为一致
    fields, spans, ht = _hit(parts, ["vite", "hmr"])
    assert ht == {"vite", "hmr"}
    assert fields == ["title", "tags"]          # "vite" 同时现于 title 与 tags
    assert spans and all(len(s) == 2 for s in spans)
    # 部分命中: 未命中 token 不再一票否决, 只返回已命中部分
    fields, spans, ht = _hit(parts, ["vite", "webpack"])
    assert ht == {"vite"}
    assert fields == ["title", "tags"]          # spans 只覆盖 "vite"
    # 零命中: 三空
    assert _hit(parts, ["webpack", "rollup"]) == ([], [], set())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_search_eval.py::test_hit_returns_triple_with_hit_tokens -v`
Expected: FAIL —— `ValueError: not enough values to unpack (expected 3, got 2)`

- [ ] **Step 3: 实现三态 `_hit` 并适配两个调用点**

`src/kb/search.py` 中把整个 `_hit` 函数(L68-91)替换为:

```python
def _hit(parts, tokens: list[str]) -> tuple[list[str], list[list[int]], set[str]]:
    """AND 分词匹配, 三态返回 (fields, spans, hit_tokens)。

    全命中: hit_tokens == set(tokens), fields/spans 与旧实现逐字节一致;
    部分命中: hit_tokens 非空但缺 token, fields/spans 只覆盖已命中 token
    (spec 2026-11-13 §3.1: 供 evaluate 降级分支复用, 不重扫 haystack);
    零命中: ([], [], set())。spans 收集全部命中 token 的全部出现位置并按
    起点排序; hit_fields 按字段首现顺序。hay 拼接与旧实现一致(各段无条件
    空格拼接, 空段同样产生分隔空格)。
    """
    hay, bounds, pos = " ".join(text for _, text in parts), [], 0
    for name, text in parts:
        bounds.append((name, pos, pos + len(text)))
        pos += len(text) + 1
    spans: list[list[int]] = []
    hit_tokens: set[str] = set()
    for tok in tokens:
        tok_spans = _token_spans(hay, tok)
        if not tok_spans:
            continue
        hit_tokens.add(tok)
        spans.extend(tok_spans)
    if not hit_tokens:
        return [], [], set()
    spans.sort()
    fields: list[str] = []
    for i, j in spans:
        for name, s, e in bounds:
            if i < e and j > s and name not in fields:
                fields.append(name)
    return fields, spans, hit_tokens
```

同文件 `evaluate` 主循环调用点(原 L162-165)替换为(本任务只适配解包并显式维持严格 AND, Task 2 再重写该循环):

```python
        fields, spans, hit_tokens = (
            ([], [], set()) if not tokens else _hit(_parts(rec), tokens))
        if tokens and hit_tokens != set(tokens):
            n_query += 1
            continue
```

`scripts/noise-gate.py` 的 `ranked()`(L62-70)同步改: 旧代码 `fields, spans = _hit(...)` 后**用 `if fields:` 判命中**——三态化后部分命中的 fields 同样非空, 只改解包会静默放宽该脚本的判定口径。L65-66 两行一起替换为(显式全命中判据, 语义与旧 `_hit` 的"fields 非空"严格等价):

```python
        fields, spans, ht = _hit(_parts(rec), toks)
        if ht == set(toks):
```

- [ ] **Step 4: 跑全量检索测试确认绿(行为不变)**

Run: `python -m pytest tests/test_search_eval.py tests/test_search_cjk_keywords.py tests/test_search_ranking.py -v`
Expected: 全部 PASS(含新测试)。重点核对既有用例逐条仍绿: `test_token_missing_means_no_match`(部分命中仍被严格 AND 拒)、`test_multiword_and_semantics`(AND 语义不变)、`test_missing_index_returns_empty`(report 键集未动)。

- [ ] **Step 5: Commit**

```powershell
git add src/kb/search.py scripts/noise-gate.py tests/test_search_eval.py
git commit -m "feat(search): _hit 三态化返回 hit_tokens(行为不变, 为降级铺路)"
```

---

### Task 2: `evaluate` 降级分支 + `match_mode`/`partial` 报告

**Files:**
- Modify: `src/kb/search.py:144-178`(`evaluate` 整体重写循环与报告构造)
- Test: `tests/test_search_eval.py`(文件末尾追加)

**Interfaces:**
- Consumes: Task 1 的 `_hit(parts, tokens) -> (fields, spans, hit_tokens)`; 既有 `_score(rec, fields, spans, tokens, today)`、`_suggest(titles, tokens)`、`_filtered_out(...)`(均不动)。
- Produces: `evaluate(repo_root, *, ..., query=None) -> (rows, report)` 签名不变; report 在有 query 时新增 `match_mode: "and"|"partial"`, partial 时另有 `partial: {"min_hit": int, "tokens": int}`。Task 3 依赖 report 上的 `match_mode` 键; Task 4 依赖降级后的 rows 排序。

- [ ] **Step 1: 写失败测试(降级触发/门槛/排序/报告键)**

在 `tests/test_search_eval.py` 末尾追加(`_mk`/`_rec` 夹具已存在):

```python
# ---- spec 3.2/3.3: 降级分支与报告 ----

def test_and_hit_no_fallback_marks_and(tmp_path):
    _mk(tmp_path, [
        _rec(1, title="license 授权服务", tags=("license",), summary="设备授权"),
        _rec(2, title="license 校验", tags=("license",), summary="签名校验"),
    ])
    _, rep = search.evaluate(tmp_path, query="license 授权")
    assert rep["match_mode"] == "and"
    assert "partial" not in rep
    assert [m["id"] for m in rep["matched"]] == ["kb-x1"]  # 逐字节同旧行为


def test_partial_fallback_min_hit_and_report(tmp_path):
    # 3 个去重 token, 只有 2 个命中的条目降级放行; 全不沾的计 query 死因
    _mk(tmp_path, [
        _rec(1, title="vite hmr 抖动排查", tags=("vite",), summary="热更新失效"),
        _rec(2, title="完全无关", tags=("x",), summary="无关"),
    ])
    rows, rep = search.evaluate(tmp_path, query="vite hmr 不存在词")
    assert [m["id"] for m in rep["matched"]] == ["kb-x1"]
    assert rep["match_mode"] == "partial"
    assert rep["partial"] == {"min_hit": 2, "tokens": 3}
    assert rep["rejected"] == {"filter": 0, "query": 1}
    assert rep["rejected"]["filter"] + rep["rejected"]["query"] \
        + len(rep["matched"]) == rep["scanned"]           # 恒等式
    assert [r["id"] for r in rows] == ["kb-x1"]


def test_partial_below_min_hit_stays_zero(tmp_path):
    # 4 token 仅 1 命中 < min_hit=2 → 仍零命中, 该条计入 rejected.query, 附 suggest
    _mk(tmp_path, [_rec(1, title="vite hmr 抖动", tags=("vite",), summary="")])
    rows, rep = search.evaluate(tmp_path, query="vite webpack rollup jest")
    assert rows == [] and rep["matched"] == []
    assert rep["match_mode"] == "partial"
    assert rep["rejected"] == {"filter": 0, "query": 1}
    assert "suggest" in rep                                # 降级后仍零命中照给建议


def test_single_token_never_downgrades(tmp_path):
    _mk(tmp_path, [_rec(1, title="vite hmr", tags=("vite",), summary="")])
    assert search.search(tmp_path, query="webpack") == []
    _, rep = search.evaluate(tmp_path, query="webpack")
    assert rep["match_mode"] == "and"                      # 单 token 无 AND 可放宽


def test_partial_ranking_ratio_then_score(tmp_path):
    # 排序先看命中比例档再看 score: A 命中 2/4 但字段权重最高(16 分级),
    # 仍排在命中 3/4 的 B/C 之后; B/C 同档(3/4)再按 score 分先后(gamma 在
    # title 的 B 压过 gamma 只在 tags 的 C)
    _mk(tmp_path, [
        _rec(1, title="alpha beta", tags=("alpha", "beta"), summary=""),
        _rec(2, title="gamma", tags=("x",), summary="alpha beta 提及"),
        _rec(3, title="低", tags=("gamma",), summary="alpha delta 提及"),
    ])
    _, rep = search.evaluate(tmp_path, query="alpha beta gamma delta")
    assert [m["id"] for m in rep["matched"]] == ["kb-x2", "kb-x3", "kb-x1"]
    assert rep["match_mode"] == "partial"


def test_partial_tie_index_order(tmp_path):
    # spec 4.1"同分 index 序": 两条命中比例与 score 完全相同(同字段同 updated),
    # 按 index 升序稳定输出
    _mk(tmp_path, [
        _rec(1, title="甲 alpha", tags=("beta",), summary=""),
        _rec(2, title="乙 alpha", tags=("beta",), summary=""),
    ])
    _, rep = search.evaluate(tmp_path, query="alpha beta gamma")
    assert [m["id"] for m in rep["matched"]] == ["kb-x1", "kb-x2"]


def test_no_query_report_unchanged(tmp_path):
    _mk(tmp_path, [_rec(1)])
    _, rep = search.evaluate(tmp_path)
    assert set(rep) == {"scanned", "rejected", "matched"}  # 兼容红线不加键
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_search_eval.py -v -k "partial or fallback or single_token or ratio or no_query_report"`
Expected: 新测试全部 FAIL(`match_mode` 键不存在 / 降级结果集为空); 既有测试仍绿。

- [ ] **Step 3: 重写 `evaluate`**

`src/kb/search.py` 中把整个 `evaluate` 函数(L144-178)替换为:

```python
def evaluate(repo_root: Path, *, type=None, domain=None, tag=None, scope=None,
             status=None, confidence=None, query=None) -> tuple[list[dict], dict]:
    """全量评估(不截断): 返回 (命中行[按分数降序], 死因报告)。

    恒等式: rejected.filter + rejected.query + len(matched) == scanned。
    report 供 trace 埋点消费; rows 与改造前 search() 元素同形, 但**有查询词时
    按 score 降序**(FR-3.1), 无查询词保持 index 序。零命中时 report 附
    `suggest` 近似词(FR-3.2), 供 MCP 透传与面板"已消化"判定。

    部分命中降级(spec 2026-11-13): 严格 AND 有结果时行为逐字节不变; 仅当
    AND 零结果且去重 token ≥2 时, 放行命中 ≥min(2, n_uniq) 个 token 的条目,
    按(命中比例档降序, score 降序, index 升序)排序——描述式长查询不再全 AND
    硬拒(hit_rate W46 35.1%), 同时比例档在前保证 3/4 命中稳定压过 1/4 命中。
    """
    recs = _load(repo_root)
    tokens = query.lower().split() if query else []
    today = dt.date.today().isoformat()  # 时效基准取当日(索引无构建时间字段)
    uniq = set(tokens)
    and_hits: list[tuple[float, int, dict, list[str], list[list[int]]]] = []
    cands: list[tuple[set[str], int, dict, list[str], list[list[int]]]] = []
    n_filter = n_no_hit = 0
    for order, rec in enumerate(recs):
        if _filtered_out(rec, type, domain, tag, scope, status, confidence):
            n_filter += 1
            continue
        fields, spans, hit_tokens = (
            ([], [], set()) if not tokens else _hit(_parts(rec), tokens))
        if hit_tokens == uniq:                 # 无 query 时两侧同为空集, 走此支
            and_hits.append((_score(rec, fields, spans, tokens, today),
                             order, rec, fields, spans))
        elif hit_tokens:
            cands.append((hit_tokens, order, rec, fields, spans))
        else:
            n_no_hit += 1
    report_partial = None
    if not tokens or and_hits or len(uniq) < 2:
        # AND 有结果(或无可放宽空间): 逐字节旧路径, 单 token 永不降级
        match_mode = "and" if tokens else None
        hits = sorted(and_hits, key=lambda h: (-h[0], h[1]))
        n_query = n_no_hit + len(cands)        # 部分命中在 AND 模式下同样死于 query
    else:
        match_mode = "partial"
        min_hit = min(2, len(uniq))
        scored = []
        for hit_tokens, order, rec, fields, spans in cands:
            if len(hit_tokens) < min_hit:
                continue
            score = _score(rec, fields, spans, sorted(hit_tokens), today)
            ratio = round(len(hit_tokens) / len(uniq), 6)
            scored.append((-ratio, -score, order, score, rec, fields, spans))
        scored.sort()                          # order 全局唯一, 天然打破元组平分
        hits = [(h[3], h[2], h[4], h[5], h[6]) for h in scored]
        n_query = n_no_hit + (len(cands) - len(scored))  # 低于门槛也计 query 死因
        report_partial = {"min_hit": min_hit, "tokens": len(uniq)}
    matched = [{"id": h[2]["id"], "title": h[2].get("title"), "scope": h[2].get("scope"),
                "confidence": h[2].get("confidence"), "hit_fields": h[3],
                "hit_spans": h[4], "score": h[0], "rank": i + 1}
               for i, h in enumerate(hits)]
    rows = [h[2] for h in hits]
    report = {"scanned": len(recs),
              "rejected": {"filter": n_filter, "query": n_query},
              "matched": matched}
    if match_mode:
        report["match_mode"] = match_mode
    if report_partial:
        report["partial"] = report_partial
    if tokens and not hits:
        report["suggest"] = _suggest([r.get("title", "") for r in recs], tokens)
    return rows, report
```

- [ ] **Step 4: 跑全量检索相关测试确认绿**

Run: `python -m pytest tests/test_search_eval.py tests/test_search_cjk_keywords.py tests/test_search_ranking.py tests/test_layers.py -v`
Expected: 全部 PASS。重点核对兼容红线: `test_missing_index_returns_empty`(`rep ==` 精确相等, 无 query 不加键)、`test_multiword_and_semantics`(AND 模式下 `rejected == {"filter": 0, "query": 2}` 不变)、`test_token_missing_means_no_match`(2 token 1 命中 < min_hit=2 → 仍零命中)、`test_cjk_sparse_noise_rejected`(单 token 不降级 → 仍 `== []`)。若 `tests/test_layers.py` 不存在则去掉该路径, 改跑 `python -m pytest tests/ -x -q` 全量。

- [ ] **Step 5: Commit**

```powershell
git add src/kb/search.py tests/test_search_eval.py
git commit -m "feat(search): AND 零结果时部分命中降级 + match_mode/partial 报告"
```

---

### Task 3: trace 事件透传 `match_mode`

**Files:**
- Modify: `src/kb/trace.py:557-560`(`build_search_event` 的 layers 白名单)
- Test: `tests/test_trace_layers.py:71-72`(改精确键集断言)与文件末尾追加

**Interfaces:**
- Consumes: Task 2 的 report 键 `match_mode`(search 层可能缺该键——limit≤0 短路与无 query 场景——故必须用 `.get`)。
- Produces: search 事件 `layers[i]["match_mode"]`(值 `"and"|"partial"|None`)。聚合层(hit_rate/consume_rate)不读该键, 口径不变; `_coerce` 只净化 `layers[].matched` 内部, 不删 layer 标量键, 读侧无需改动。

- [ ] **Step 1: 更新既有精确键集断言 + 写失败测试**

`tests/test_trace_layers.py` 中 `test_build_search_event_shape` 内(L71-72)的:

```python
    assert set(ev["layers"][0]) == {"repo", "scanned", "rejected", "matched",
                                    "taken", "truncated_at_limit"}
```

替换为:

```python
    assert set(ev["layers"][0]) == {"repo", "scanned", "rejected", "matched",
                                    "taken", "truncated_at_limit", "match_mode"}
    assert ev["layers"][0]["match_mode"] == "and"   # query="vite" AND 有命中
```

文件末尾追加:

```python
def test_build_search_event_carries_partial_mode(tmp_path):
    # AND 零结果走降级(仍零命中也标 partial), 事件必须带 match_mode 供归因
    docs = _mk(tmp_path, "docs", [_rec(1, "vite hmr 抖动", tags=["vite"])])
    _, rep = search.evaluate(docs, query="vite webpack")
    rep.update({"repo": "docs", "taken": 0, "truncated_at_limit": False})
    ev = trace.build_search_event(
        trace_id="t-2", source="mcp", caller_repo="web", query="vite webpack",
        filters={}, limit=10, reports=[rep], returned=[], duration_ms=3)
    assert ev["layers"][0]["match_mode"] == "partial"


def test_build_search_event_legacy_report_without_match_mode(tmp_path):
    # limit≤0 短路的 report 与历史数据无 match_mode 键: 透传 None 不 KeyError
    ev = trace.build_search_event(
        trace_id="t-3", source="mcp", caller_repo="web", query="vite",
        filters={}, limit=0,
        reports=[{"repo": "docs", "scanned": 0,
                  "rejected": {"filter": 0, "query": 0}, "matched": [],
                  "taken": 0, "truncated_at_limit": False}],
        returned=[], duration_ms=1)
    assert ev["layers"][0]["match_mode"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trace_layers.py -v`
Expected: 3 个用例 FAIL —— 键集断言少 `match_mode`; 两个新用例 `KeyError: 'match_mode'`(或第一个断言失败)。

- [ ] **Step 3: 白名单加键**

`src/kb/trace.py` `build_search_event` 内(L557-560)的:

```python
        "layers": [{"repo": r["repo"], "scanned": r["scanned"],
                    "rejected": r["rejected"], "matched": r["matched"],
                    "taken": r["taken"], "truncated_at_limit": r["truncated_at_limit"]}
                   for r in reports],
```

替换为:

```python
        "layers": [{"repo": r["repo"], "scanned": r["scanned"],
                    "rejected": r["rejected"], "matched": r["matched"],
                    "taken": r["taken"], "truncated_at_limit": r["truncated_at_limit"],
                    # 部分命中降级归因(spec 2026-11-13 §3.3); limit≤0 短路与
                    # 历史 report 无该键 → None, 聚合口径不读它, hit_rate 不变
                    "match_mode": r.get("match_mode")}
                   for r in reports],
```

- [ ] **Step 4: 跑 trace 相关测试确认绿**

Run: `python -m pytest tests/test_trace_layers.py tests/test_trace.py -v`
Expected: 全部 PASS(若 `tests/test_trace.py` 不存在则去掉该路径, 改跑 `python -m pytest tests/ -x -q`)。确认无任何聚合测试因新键变红——若有, 说明该测试同样做了精确键集断言, 按同样方式补键而非改聚合代码。

- [ ] **Step 5: Commit**

```powershell
git add src/kb/trace.py tests/test_trace_layers.py
git commit -m "feat(trace): search 事件 layers 透传 match_mode"
```

---

### Task 4: 离线回放验收脚本 `scripts/replay-partial-hit.py`

**Files:**
- Create: `scripts/replay-partial-hit.py`
- Test: 无 pytest 单测(脚本即验收工具, 参照 `scripts/noise-gate.py` 同为可复现判据脚本的先例); 本任务的"测试"就是运行脚本本身。

**Interfaces:**
- Consumes: Task 1/2 后的 `kb.search._hit/_parts/_score/evaluate`; 既有 `kb.stats.effective(searches) -> list`、`kb.stats.denoise(searches, gets) -> (searches, gets, n, callers)`; `traces/*.jsonl` 的 search 事件(`kind/query/ts/caller_repo`)。
- Produces: 退出码 0=PASS / 1=FAIL / 2=无语料; stdout 打印总 hit_rate 对比与 W{week} 达标情况。不进 CI, 人工验收用。

- [ ] **Step 1: 写脚本(完整内容)**

创建 `scripts/replay-partial-hit.py`:

```python
"""部分命中降级离线回放 — spec 2026-11-13 §4.2 验收门槛的可复现实现。

对 traces/*.jsonl 的历史**有效** query(剔 not_executed 与合成 caller), 在
**当前** kb/index.jsonl 上把新旧两种策略各重放一遍再对比(索引自查询当日
有演进, 只与"同索引下旧策略结果"比, 不与 trace 记录的历史 returned 比):
  1) 旧策略(纯 AND)命中的查询, 新策略结果集与排序 100% 不变;
  2) --week 指定 ISO 周时, 该周新策略 hit_rate ≥ 50%(W46 基线 35.1%);
  3) 打印新旧总 hit_rate 供人工确认"显著提升"。

用法:
  python scripts/replay-partial-hit.py              # 全量语料
  python scripts/replay-partial-hit.py --week 46    # 附 W46 达标判据

退出码: 0=PASS; 1=FAIL(回退或未达标); 2=输入不可用(缺生成物/无语料)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kb.search import _hit, _parts, _score, evaluate  # noqa: E402
from kb.stats import denoise, effective  # noqa: E402


def load_index(repo: Path) -> list[dict]:
    jl = repo / "kb" / "index.jsonl"
    if not jl.exists():
        print(f"缺生成物: {jl}", file=sys.stderr)
        sys.exit(2)
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_searches(traces: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(traces.glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "search":
                out.append(rec)
    return out


def iso_week(ts: str) -> int | None:
    try:
        return dt.datetime.fromisoformat(ts).isocalendar()[1]
    except (TypeError, ValueError):
        return None


def old_policy_ids(recs: list[dict], toks: list[str], today: str) -> list[str]:
    """旧策略: 全 token AND 命中, (-score, index) 排序。与改造前 evaluate
    逐字节等价(_hit 全命中时 fields/spans 同旧值)。"""
    scored = []
    for order, rec in enumerate(recs):
        fields, spans, ht = _hit(_parts(rec), toks)
        if ht == set(toks):
            scored.append((-_score(rec, fields, spans, toks, today), order, rec["id"]))
    scored.sort()
    return [rid for _, _, rid in scored]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="kb 库根(含 kb/index.jsonl)")
    ap.add_argument("--traces", default="traces", help="trace 语料目录")
    ap.add_argument("--week", type=int, default=None, help="ISO 周号(启用达标判据)")
    ap.add_argument("--week-target", type=float, default=0.50, help="达标线, 默认 0.50")
    args = ap.parse_args()

    repo, traces = Path(args.repo), Path(args.traces)
    if not traces.exists():
        print(f"缺语料目录: {traces}", file=sys.stderr)
        sys.exit(2)
    recs = load_index(repo)
    today = dt.date.today().isoformat()

    searches = [s for s in effective(denoise(load_searches(traces), [])[0]) if s.get("query")]
    if not searches:
        print("无语料: traces 里没有有效 search 事件", file=sys.stderr)
        sys.exit(2)

    regressions: list[tuple[str, list[str], list[str]]] = []
    old_hit = new_hit = 0
    week_total = week_hit = 0
    seen: set[str] = set()
    for s in searches:
        q = s["query"]
        toks = q.lower().split()
        if not toks:
            continue
        old_ids = old_policy_ids(recs, toks, today)
        new_ids = [r["id"] for r in evaluate(repo, query=q)[0]]
        if old_ids:
            old_hit += 1
            if old_ids != new_ids:            # 判据 1: 原命中查询结果与排序逐字节不变
                regressions.append((q, old_ids, new_ids))
        if new_ids:
            new_hit += 1
        wk = iso_week(s.get("ts", ""))
        if wk is not None and wk == args.week:
            week_total += 1
            week_hit += bool(new_ids)

    n = len(searches)
    print(f"有效查询 {n} 条 | 旧 hit_rate {old_hit / n:.1%} → 新 hit_rate {new_hit / n:.1%}")
    if args.week:
        if not week_total:
            print(f"W{args.week} 无有效查询样本, 达标判据无法评估")
            return 2
        rate = week_hit / week_total
        ok = rate >= args.week_target
        print(f"W{args.week}: {week_hit}/{week_total} = {rate:.1%}"
              f"（目标 ≥{args.week_target:.0%}）→ {'PASS' if ok else 'FAIL'}")
        if not ok:                                   # 判据 2 未达标即 FAIL, 不能只打印
            return 1
    if regressions:
        print(f"回退 {len(regressions)} 条(旧命中但新结果/排序变了):")
        for q, old, new in regressions[:10]:
            print(f"  {q!r}: {old} -> {new}")
        return 1
    print("判据 1 PASS: 旧命中查询结果集与排序 100% 不变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑脚本确认 PASS 基线**

Run: `python scripts/replay-partial-hit.py --week 46`
Expected: 退出码 0；打印"判据 1 PASS"与 W46 命中率达标（新 hit_rate 显著高于旧值；W46 ≥ 50%）。若判据 1 出现回退条目，回到 Task 2 检查 AND 有结果分支是否严格走了旧路径（常见错因：把"AND 有结果"与"AND 零结果"的排序键混写）。若脚本退出码 2（无 W46 样本），改用 `--week` 换成语料中实际存在的周号再跑，并在验收记录中注明实际口径。

- [ ] **Step 3: Commit**

```powershell
git add scripts/replay-partial-hit.py
git commit -m "test(search): 部分命中降级离线回放脚本(验收三门槛)"
```

---

### Task 5: 全量回归与索引校验

**Files:**
- 无新建/修改文件(纯验证任务)。

**Interfaces:**
- Consumes: Task 1-4 全部落地后的工作区。
- Produces: 三个验收命令全绿的证据(用于 PR/收尾说明)。

- [ ] **Step 1: 全量单测**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS，无新增 fail/skip 变化。特别确认 MCP 层测试无新增断言失败。

- [ ] **Step 2: 索引校验**

Run: `kb lint --scope agent-kb --repo .`
Expected: 退出码 0。

- [ ] **Step 3: 索引漂移检查**

Run: `kb index --check --repo .`
Expected: 退出码 0（`match_mode` 是运行时 report 字段，不进 index.jsonl，生成物零变更——本步骤就是确认这一 spec 约束落地）。

- [ ] **Step 4: 工作区卫生确认**

Run: `git status --short`
Expected: 仅剩 `traces/` 下文件（如有，属定时任务产物，**不纳入提交**）；无未跟踪的非预期文件。

---

## 验收对照(spec §4)

| spec 要求 | 落地任务 |
| --- | --- |
| §3.1 `_hit` 三态 | Task 1 |
| §3.2 降级分支(触发条件/门槛/排序) | Task 2 |
| §3.3 `match_mode`/`partial` 报告 + trace 透传 + 恒等式 | Task 2 + Task 3 |
| §3.4 调用点同步 | Task 1(noise-gate.py:65) + Task 2(evaluate) |
| §4.1 单测(三态/触发/排序/恒等式/既有全绿) | Task 1-3 + Task 5 |
| §4.2 离线回放三门槛 | Task 4 |
| §4.3 kb lint / index --check | Task 5 |
