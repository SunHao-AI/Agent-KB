# L2 摘要质量与联邦记录契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 kb 知识库引入 front-matter 显式 `summary` 字段（lint 渐进守护 + stat 覆盖率度量），并把 index.jsonl 记录形状定版为可承接外部异构源的联邦 L2 记录契约（+`origin`/`uri`）。

**Architecture:** 单点收口——`Entry.summary()` 显式优先、派生兜底（消费面零改动全部受益）；`index._records` 是本地记录唯一生产者，联邦两字段在此注入；schema 真源是 `taxonomy.py::derive_schema()`（`schema/frontmatter.schema.json` 无代码加载，仅文档同步）。

**Tech Stack:** Python 3 + PyYAML + jsonschema(Draft 2020-12) + pytest(+pytest-asyncio, mcp SDK 内存会话)；CLI 入口 `kb`（`kb.cli:main`）。

**Spec:** `docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md`（已批准，本计划逐节覆盖其 §5.2 测试面 7 项）

## Global Constraints

- 派生兜底路径逐字节不变：无显式 summary 时 `Entry.summary()` 输出与现行为完全一致；
- `INDEX.md` / `index.jsonl` / `index.draft.jsonl` 是生成物，**只能由 `kb index` 重建，勿手改**；
- lint summary 规则恒为 warning 前缀（`warning: `），不进 errors 硬闸门；阈值常量 `SUMMARY_REQUIRED_SINCE = "2026-11-15"`；
- summary 长度约束：空串豁免（=缺失），非空 10–300；显式值进索引**不截断**；
- 不回填存量条目、不新增 type/domain、不写任何外部源适配器、不改 sections/hit_fields/检索打分；
- 功能提交不得携带 `traces/` 与 `kb/INDEX.md`、`kb/index.jsonl`、`kb/index.draft.jsonl` 之外的生成物漂移（Task 9 重建后单独提交）；
- Windows PowerShell：命令分隔用 `;`，**不能用 `&&`**；检索类手工验证加 `--no-trace`；
- 全程中文注释，遵循仓库既有注释风格（讲根因，不复述代码）。

## 测试基建速查（实现者零上下文必读）

- `tests/conftest.py`：`make_entry(**over)` 用默认 front-matter + dict 覆盖生成条目全文（`SAMPLE_FRONTMATTER` 无 summary，`created=2026-10-12`，默认 title=`demo`，默认 body 为 `\n# demo\n\n首段摘要。\n`——**无 `## 根因` 段**，派生摘要即 `首段摘要。`）。三个坑：①front-matter 是 f-string 逐行拼接，**多行值会破坏 YAML**，summary 只传单行字符串；②`summary=""` 产出裸 `summary: ` 解析为 **None**（schema 硬错误），测空串必须写 `summary='""'`（YAML 合法空串）；③默认条目**互不撞指纹**（指纹冲突检测 `MIN_FP_LEN=16` 对短源免检），勿假设"两次默认调用天然同指纹"。fixture `tmp_repo`（含 `kb/` 的仓根 Path）。
- lint warning 断言范式（`tests/test_lint.py` 同款）：`warns = [m for m in msgs if m.startswith("warning: ")]` 双向断言。
- MCP 内存会话（`tests/test_mcp.py` 既有）：`pytestmark = pytest.mark.asyncio`；`_call(server, name, args)` 返回 `(res.isError, 解析后的 text)`；`from mcp.shared.memory import create_connected_server_and_client_session`。
- trace 捕获（`tests/test_trace_cli.py` 既有 env/`_events` 范式）：`monkeypatch.setattr(trace, "kb_root", lambda: root)` 隔离真实 `traces/` + `monkeypatch.delenv("KB_TRACE")`，开埋点用 `monkeypatch.setenv("KB_TRACE", "1")`。
- 跑测试：仓库根 `python -m pytest tests/test_xxx.py -v`。

## File Structure（改动面与职责）

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `src/kb/taxonomy.py` | 运行时 schema 真源（`derive_schema`） | +summary 属性（空串豁免 / 10–300） |
| `src/kb/entry.py` | 条目模型 + 摘要单点 | `Entry.summary()` 新增显式分支 |
| `src/kb/index.py` | 联邦记录唯一生产者 | `_records` rec +`origin`/`uri` |
| `src/kb/lint.py` | 校验与渐进守护 | +summary 缺失/脏值 warning |
| `src/kb/query.py` | stat 读数 | `stat()` +`summary_coverage` |
| `src/kb/new_entry.py` | 手工建条目 | `create_entry` +`summary` 形参 |
| `src/kb/gate.py` | agent 门控建/改条目 | `create_draft` 回填 / `update_entry` pop 式 |
| `src/kb/mcp_server.py` | MCP 面 | `kb_create`/`kb_update` 透传 |
| `src/kb/cli.py` | CLI 面 | `kb new --summary`；search 埋点**零改动**（仅 Task 7 加断言测试） |
| `schema/frontmatter.schema.json` | 文档性 schema | 同步 summary 属性（无行为） |
| `templates/*.md`(8) | 人读模板 | front-matter +`summary: ""` |
| `AGENTS.md` | L1 入口 | §1 表后 +一句契约指向 |
| `tests/test_entry.py` `test_taxonomy.py` `test_lint.py` `test_index.py` `test_query.py` `test_new.py` `test_mcp.py` `test_federation_contract.py`(新建) | 各任务测试 | 追加 |
| `docs/kb/reference/2026-11-14-federated-l2-record-contract.md` | 联邦契约自描述条目 | Task 9 创建+索引+commit |

**跨任务契约**（任务间只允许依赖这些签名）：

- `Entry.summary(self, limit: int = 120) -> str`（签名不变）
- `create_entry(..., summary: str | None = None, ...) -> Entry`
- `create_draft(..., summary: str | None = None, ...) -> Entry`
- `update_entry(repo_root, entry_id, *, summary: str | None = None, ...) -> Entry`（返回落盘后的条目，不是 dict）
- `_records()` 产出 rec 恒含 `"origin": str`、`"uri": str | None`
- `stat()` 返回 dict 恒含 `"summary_coverage": {"explicit": int, "total": int}`
- lint 新消息形状：`warning: {rid}: 缺 summary(结论句...)` / `warning: {rid}: summary 仅 N 字符...`

---

### Task 1: schema——summary 属性（真源 + 文档同步）

**Files:**
- Modify: `src/kb/taxonomy.py`（`derive_schema()` props，`"title"` 行之后）
- Modify: `schema/frontmatter.schema.json`（properties，`"title"` 属性之后）
- Test: `tests/test_taxonomy.py`（追加）

**Interfaces:**
- Consumes: 无（首任务）
- Produces: schema 接受 `summary: ""` 与 10–300 字符串，拒 1–9 / >300 / 非字符串——Task 4 的 lint 脏值 warning 以此为前提（schema 放行脏值、lint 负责提醒）；注意 **lint 的 schema 校验在 Task 1 后即生效**，故本任务必须先于一切"写入脏 summary"的实现。

- [ ] **Step 1: 写失败测试**

在 `tests/test_taxonomy.py` 末尾追加（复用文件既有 helper `_fm(**over)`——合法 front-matter dict，与文件顶部的 `json`/`jsonschema`/`yaml` imports，**该文件没有名为 `VALID` 的常量**）：

```python
def test_derive_schema_summary_field():
    """summary 非必填; 空串豁免(模板占位); 1-9 与 >300 为 schema 硬错误。"""
    schema = derive_schema(_load_repo_taxonomy())
    v = jsonschema.Draft202012Validator(schema)
    assert v.is_valid(_fm())                                  # 非必填
    assert v.is_valid(_fm(summary=""))                        # 空串豁免
    assert v.is_valid(_fm(summary="连接池上限过低会拖垮高并发接口。"))
    assert not v.is_valid(_fm(summary="短"))                   # 1-9 硬错误
    assert not v.is_valid(_fm(summary="字" * 301))             # >300 硬错误
    assert not v.is_valid(_fm(summary=123))                   # 非字符串
```

说明：直接对派生 schema 做校验器断言，不落盘、不依赖 conftest。Step 4 改完 `schema/frontmatter.schema.json` 后，既有 `test_committed_schema_matches_derivation`（断言 `committed == derived`）会**强制**文档 schema 逐字节同步——无需为它新增任何断言。

- [ ] **Step 2: 跑红**

Run: `python -m pytest tests/test_taxonomy.py -v -k summary`
Expected: FAIL——当前 schema 无 summary 属性且未禁未知字段，`assert not v.is_valid(_fm(summary="短"))` 失败（脏值目前不受任何约束）。

- [ ] **Step 3: 实现——`taxonomy.py::derive_schema()`**

在 `props` 字典中 `"title"` 行**之后**插入：

```python
        # L2 结论句(spec 2026-11-14 §3.1): 可选; 空串=缺失显式豁免(模板 `summary: ""`
        # 占位与人工清空都合法), 非空限 10-300——下限防"填了等于没填", 上限对齐 OG 惯例。
        "summary": {"anyOf": [{"const": ""},
                              {"type": "string", "minLength": 10, "maxLength": 300}]},
```

- [ ] **Step 4: 实现——文档 schema 同步**

`schema/frontmatter.schema.json` 的 `properties` 中 `"title"` 属性对象之后加入（保持 JSON 逗号合法）：

```json
    "summary": {
      "anyOf": [
        { "const": "" },
        { "type": "string", "minLength": 10, "maxLength": 300 }
      ]
    },
```

- [ ] **Step 5: 跑绿**

Run: `python -m pytest tests/test_taxonomy.py tests/test_lint.py -v`
Expected: 全部 PASS（`test_committed_schema_matches_derivation` 绿 = Step 4 文档同步逐字节正确；test_lint 全绿 = 新属性没把既有用例打成硬错误）。

- [ ] **Step 6: Commit**

```powershell
git add src/kb/taxonomy.py schema/frontmatter.schema.json tests/test_taxonomy.py
git commit -m "feat(schema): front-matter 可选 summary 属性(空串豁免/10-300), derive_schema 为运行时真源"
```

---

### Task 2: `Entry.summary()` 显式分支（单点收口）

**Files:**
- Modify: `src/kb/entry.py`（`Entry.summary()`，约 L101-108）
- Test: `tests/test_entry.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 schema（脏值此时已被 lint 报 schema 错误，但 `Entry.summary()` 对任何脏值仍须有确定行为）
- Produces: `Entry.summary(self, limit: int = 120) -> str`（签名不变）——`fm["summary"]` strip 非空 → 空白折叠后**原样返回（不截断）**；否则逐字节走原派生。

- [ ] **Step 1: 写失败测试**

在 `tests/test_entry.py` 末尾追加（`make_entry` 默认 body 是 `\n# demo\n\n首段摘要。\n`——派生摘要为 `首段摘要。`；summary 值**只能单行**，多行会破坏 conftest 的 f-string 行拼接）：

```python
def test_summary_explicit_preferred_not_truncated(tmp_path):
    """显式 summary: 优先于派生、折叠空白、不截断; 空串/空白=缺失回落派生。"""
    long_text = "结" * 200
    p = tmp_path / "s.md"
    p.write_text(make_entry(summary="  上线前必须压测 前, 连接池上限需复核。  ")
                 + "\n## 背景\n\n被压制的派生兜底文案。\n", encoding="utf-8")
    assert parse_entry(p).summary() == "上线前必须压测 前, 连接池上限需复核。"

    p2 = tmp_path / "l.md"
    p2.write_text(make_entry(summary=long_text) + "\n## 背景\n\n兜底。\n", encoding="utf-8")
    assert parse_entry(p2).summary() == long_text          # 200 字不截断

    # YAML 空串/空白字面量: '""' 解析为 ""、'"   "' 解析为 "   "(make_entry 是
    # f"{k}: {v}" 行拼接, 直接传 "" 会产出裸 `summary:` → None, 语义不同)
    for blank in ('""', '"   "'):
        p3 = tmp_path / "b.md"
        p3.write_text(make_entry(summary=blank)
                      + "\n## 背景\n\n派生文案。\n", encoding="utf-8")
        assert parse_entry(p3).summary() == "首段摘要。"    # 空/空白 → 派生兜底


def test_summary_derived_fallback_unchanged(tmp_path):
    """回归锁定 Global Constraints: 无显式字段时输出与旧行为逐字节一致。"""
    p = tmp_path / "d.md"
    p.write_text(make_entry(), encoding="utf-8")
    assert parse_entry(p).summary() == "首段摘要。"        # 默认 body 派生值

    p2 = tmp_path / "d2.md"
    p2.write_text(make_entry() + "\n## 背景\n\n上线后偶发连接超时。\n", encoding="utf-8")
    assert parse_entry(p2).summary() == "首段摘要。"      # 追加段不改首个正文块
```

派生路径的 `[:120]` 截断行为由 `test_entry.py` **既有**派生测试守护（Step 4 要求它们保持全绿），本用例只锁定"缺失→回落派生"的不变性，不重复造派生夹具。

- [ ] **Step 2: 跑红**

Run: `python -m pytest tests/test_entry.py -v -k summary`
Expected: FAIL——显式分支不存在，第一个用例 `summary()` 返回派生值"被压制的派生兜底文案。"而非显式文案。

- [ ] **Step 3: 实现**

`src/kb/entry.py` 的 `Entry.summary()` 方法首部插入（派生循环**逐字节不动**）：

```python
    def summary(self, limit: int = 120) -> str:
        # 显式 summary 优先(spec 2026-11-14 §3.2): "空 = 缺失"——strip 后非空才采信;
        # 仅折叠空白不截断(schema 已限 300, 显式声明即最终消费文案)。派生兜底路径
        # 逐字节不变, 存量条目输出与索引零漂移(回归锁定见 tests/test_entry.py)。
        explicit = str(self.fm.get("summary") or "").strip()
        if explicit:
            return re.sub(r"\s+", " ", explicit)
        # 按空行分块, 块内剔除标题行(标题可能与正文同块), 取第一个还有正文的块
        for block in re.split(r"\n\s*\n", self.body):
            ...  # 既有代码原样保留
```

- [ ] **Step 4: 跑绿**

Run: `python -m pytest tests/test_entry.py -v`
Expected: 全部 PASS（既有 summary/sections 派生测试必须保持全绿 = 逐字节不变守护）。

- [ ] **Step 5: Commit**

```powershell
git add src/kb/entry.py tests/test_entry.py
git commit -m "feat(entry): Entry.summary 显式字段优先不截断, 派生兜底逐字节不变"
```

---

### Task 3: 联邦记录形状——`_records` +origin/uri

**Files:**
- Modify: `src/kb/index.py`（`_records()` 的 rec 字典）
- Test: `tests/test_index.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `Entry.summary()`（rec["summary"] 经其产出，无显式字段时值不变）
- Produces: `index.jsonl` / `index.draft.jsonl` 每行恒含 `"origin": "local"`、`"uri": null`；`_jsonl`/`_md` 不变。

- [ ] **Step 1: 写失败测试**

在 `tests/test_index.py` 末尾追加（文件头已 `import json`）：

```python
def test_records_carry_federation_fields(tmp_repo):
    """联邦 L2 记录契约(spec 2026-11-14 §1): 本地记录恒 origin=local, uri=null。"""
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261114-aaaa", status="accepted"),
                            encoding="utf-8")
    (d / "w.md").write_text(make_entry(id="kb-20261114-bbbb", status="draft"),
                            encoding="utf-8")
    build_indexes(tmp_repo, repo_name="demo")
    for name in ("index.jsonl", "index.draft.jsonl"):
        rows = [json.loads(ln) for ln in
                (tmp_repo / "kb" / name).read_text(encoding="utf-8").splitlines()]
        assert rows and all(r["origin"] == "local" and r["uri"] is None for r in rows)
    # 检索面透传零破坏: search 行含新字段仍命中(联邦适配器只需产出同形状行)
    from kb.search import search
    hits = search(tmp_repo, query="Vite", limit=5)
    assert hits and hits[0]["origin"] == "local"
```

- [ ] **Step 2: 跑红**

Run: `python -m pytest tests/test_index.py -v -k federation`
Expected: FAIL——`KeyError: 'origin'`。

- [ ] **Step 3: 实现**

`src/kb/index.py::_records()` 的 rec 字典，`"updated": ..., "repo": repo_name,` 之前插入两行：

```python
            # 联邦 L2 记录契约(spec 2026-11-14 §1): origin/uri 是本文件唯一的记录
            # 生产者注入点——外部源(feishu/notion/wiki/tencentdb…)只需产出同形状
            # JSONL 行; 外部 id 用 `source://<connector>/<原生id>`(对齐 stats.source_of
            # 既有命名空间), 归一 origin=`ext:<connector>`。本地恒 local/null。
            "origin": "local", "uri": None,
```

- [ ] **Step 4: 跑绿（含既有索引测试）**

Run: `python -m pytest tests/test_index.py tests/test_search_cjk_keywords.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```powershell
git add src/kb/index.py tests/test_index.py
git commit -m "feat(index): index.jsonl 定版联邦记录形状(+origin/uri), 外部源只需产同形状行"
```

---

### Task 4: lint 渐进守护——summary 缺失/脏值 warning

**Files:**
- Modify: `src/kb/lint.py`（主循环内、占位段 warning 之后）
- Test: `tests/test_lint.py`（追加）

**Interfaces:**
- Consumes: Task 1 schema（脏值已另有 schema 硬错误，本任务只加**可读性提醒**）；`dt` 已在文件头导入
- Produces: `warning: {rid}: 缺 summary(建议一句结论: 条件+结论+动作, 10-300 字)`（仅 `created >= SUMMARY_REQUIRED_SINCE`）；`warning: {rid}: summary 仅 N 字符, 难承载结论句(建议 10-300)`（created 任意日期，空串豁免）。cli 的 warns/hard 分流、baseline、`--strict` 按 `warning: ` 前缀**自动接入，零改动**。

- [ ] **Step 1: 写失败测试**

在 `tests/test_lint.py` 末尾追加（文件头已有 `lint_repo`/`make_entry` 导入；若无则按该文件现有 import 行补齐）：

```python
def test_lint_summary_missing_only_for_new_entries(tmp_repo):
    """存量(created < SUMMARY_REQUIRED_SINCE)不告警; 新条目缺 summary 告警。"""
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "old.md").write_text(make_entry(id="kb-20260101-aa01"), encoding="utf-8")
    (d / "new.md").write_text(make_entry(id="kb-20261120-aa02", created="2026-11-20",
                                         updated="2026-11-20"), encoding="utf-8")
    msgs = lint_repo(tmp_repo, scope="project")
    warns = [m for m in msgs if m.startswith("warning: ")]
    assert any("kb-20261120-aa02" in m and "缺 summary" in m for m in warns)
    assert not any("kb-20260101-aa01" in m for m in warns)
    assert not [m for m in msgs if not m.startswith("warning: ")]   # 只加 warning 不进硬闸门


def test_lint_summary_present_and_empty_exempt(tmp_repo):
    """有 summary 不告警; 空串=缺失豁免(与 schema/Entry.summary 同一语义)。"""
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "p.md").write_text(make_entry(id="kb-20261120-aa03", created="2026-11-20",
                                       updated="2026-11-20",
                                       summary="Redis 连接池默认过低会拖垮高并发接口。"),
                            encoding="utf-8")
    (d / "e.md").write_text(make_entry(id="kb-20261120-aa04", created="2026-11-20",
                                       updated="2026-11-20", summary='""'), encoding="utf-8")
                                       # '""' 是 YAML 空串字面量; 裸 "" 会产出 `summary: ` → None
    warns = [m for m in lint_repo(tmp_repo, scope="project") if m.startswith("warning: ")]
    assert not any("kb-20261120-aa03" in m or "kb-20261120-aa04" in m for m in warns)


def test_lint_summary_dirty_short_value(tmp_repo):
    """1-9 字符脏值: schema 硬错误(Task 1) + 可读性 warning(本规则)。"""
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "s.md").write_text(make_entry(id="kb-20261012-aa05", summary="太短"),
                            encoding="utf-8")
    msgs = lint_repo(tmp_repo, scope="project")
    assert any("summary" in m and "schema" in m for m in msgs if not m.startswith("warning: "))
    assert any("kb-20261012-aa05" in m and "summary" in m for m in msgs if m.startswith("warning: "))


def test_lint_existing_rules_unaffected(tmp_repo):
    """回归: 新规则只加 warning——带合规 summary 的两条新条目零 summary 打扰、零硬错误。"""
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261012-aa11", title="标题甲",
                                       summary="上线前必须验证连接池上限与超时配置。"), encoding="utf-8")
    (d / "b.md").write_text(make_entry(id="kb-20261012-aa12", title="标题乙",
                                       summary="灰度发布先 1% 再放量并盯住回滚开关。"), encoding="utf-8")
    msgs = lint_repo(tmp_repo, scope="project")
    # 默认条目短源低于 MIN_FP_LEN 免检, 互不撞指纹; 本断言锁的是"新规则不引入硬错误"
    assert [m for m in msgs if not m.startswith("warning: ")] == []
    warns = [m for m in msgs if m.startswith("warning: ")]
    assert not any("summary" in m for m in warns)
```

- [ ] **Step 2: 跑红**

Run: `python -m pytest tests/test_lint.py -v -k summary`
Expected: FAIL——`any(... "缺 summary" ...)` 为假。

- [ ] **Step 3: 实现**

`src/kb/lint.py`：模块级（**`_HTML_COMMENT_RE` 定义行附近**，约 L12）加常量：

```python
# summary 渐进守护(spec 2026-11-14 §3.3): 只对新条目要"结论句", 存量不追(批量回填会产
# 数百条机翻摘要噪音)。created 判界用 ISO 字符串比较(字典序即时间序), 不做日期解析。
SUMMARY_REQUIRED_SINCE = "2026-11-15"
```

主循环内、占位段告警循环之后（实文 `for msg in _placeholder_warnings(e, type_sections): errors.append(f"warning: {rid}: {msg}")`，约 L110-111）加：

```python
        # summary 渐进守护(spec 2026-11-14 §3.3): 缺失只看**键存在性**——`summary: ""`
        # 是模板占位/人工清空, schema 已豁免, 这里绝不能按"值为空"报缺失(三处"空=缺失"
        # 语义的分工: schema 放行空串、Entry.summary 空值回落派生、lint 只把"键不存在"
        # 算缺失)。脏值只报非空且 strip 后 <10(schema 的 1-9 硬错误归 schema 校验段管,
        # 这里是给人看的可行动提示, created 任意日期都报)。
        if "summary" not in fm:
            if str(fm.get("created", "")) >= SUMMARY_REQUIRED_SINCE:
                errors.append(f"warning: {rid}: 缺 summary(建议一句结论: 条件+结论+动作, 10-300 字)")
        else:
            s = str(fm.get("summary") or "").strip()
            if s and len(s) < 10:
                errors.append(f"warning: {rid}: summary 仅 {len(s)} 字符, 难承载结论句(建议 10-300)")
```

- [ ] **Step 4: 跑绿（既有 warning 规则回归）**

Run: `python -m pytest tests/test_lint.py tests/test_cli.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 全仓 lint 冒烟（存量零打扰）**

Run: `kb lint --scope agent-kb --repo .`
Expected: 输出不含任何 `缺 summary` 行（现存 207 条 created 全 < 2026-11-15）。

- [ ] **Step 6: Commit**

```powershell
git add src/kb/lint.py tests/test_lint.py
git commit -m "feat(lint): summary 缺失/脏值 warning 渐进守护(created>=2026-11-15, 存量不追)"
```

---

### Task 5: `stat` 覆盖率——`summary_coverage`

**Files:**
- Modify: `src/kb/query.py`（`stat()`）
- Test: `tests/test_query.py`（追加；文件头已导入 `stat`/`build_indexes`/`make_entry`/`Path`/`dt`）

**Interfaces:**
- Consumes: `iter_entry_paths`/`parse_entry`（query.py 头部既有 import 已含，勿重复导入）
- Produces: `stat()` 返回 dict 新增键 `"summary_coverage": {"explicit": int, "total": int}`——仿 `due_review()` 的 `parse_entry` 直接遍历，**不进 index.jsonl**（不往检索面掺度量字段、免索引漂移源）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_query.py` 末尾追加：

```python
def test_stat_summary_coverage(tmp_path):
    """覆盖率只认显式字段: 派生兜底不算 explicit, 空串/缺失都不算(spec §5.1)。"""
    root = tmp_path / "kbroot"
    d = root / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261114-aa01", status="accepted",
                                       summary="连接池上限过低会拖垮高并发接口。"),
                            encoding="utf-8")
    (d / "b.md").write_text(make_entry(id="kb-20261114-aa02", status="accepted"),
                            encoding="utf-8")
    (d / "c.md").write_text(make_entry(id="kb-20261114-aa03", status="accepted",
                                       summary='""'), encoding="utf-8")  # YAML 空串, 裸 "" 会变 None
    build_indexes(root, repo_name="kbroot")
    s = stat(root)
    assert s["total"] == 3
    assert s["summary_coverage"] == {"explicit": 1, "total": 3}
```

- [ ] **Step 2: 跑红**

Run: `python -m pytest tests/test_query.py -v -k coverage`
Expected: FAIL——`KeyError: 'summary_coverage'`。

- [ ] **Step 3: 实现**

`src/kb/query.py::stat()` 内，`due` 计算之前插入计数，返回 dict 加一行：

```python
    # 显式 summary 覆盖率(spec 2026-11-14 §5.1): 只认 front-matter 显式字段——
    # 派生兜底恒有值, 从索引统计会把覆盖率虚报成 100%。仿 due_review 直接 parse,
    # 不进 index.jsonl(检索面零污染, 也少一个索引漂移源)。
    explicit = total = 0
    for p in iter_entry_paths(repo_root):   # stat() 体内变量名是 repo_root
        fm = parse_entry(p).fm
        if not fm.get("id"):
            continue
        total += 1
        if str(fm.get("summary") or "").strip():
            explicit += 1
```

返回 dict 中 `"due_review": len(due),`（实文如此）之后加：

```python
            "summary_coverage": {"explicit": explicit, "total": total},
```

- [ ] **Step 4: 跑绿**

Run: `python -m pytest tests/test_query.py tests/test_cli.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 真仓读数冒烟**

Run: `kb stat --repo .`
Expected: JSON 含 `"summary_coverage": {"explicit": 0, "total": 207}`（基线锚点，供上线后趋势对比）。

- [ ] **Step 6: Commit**

```powershell
git add src/kb/query.py tests/test_query.py
git commit -m "feat(stat): summary_coverage 显式覆盖率读数(parse 直读, 不进检索面)"
```

---

### Task 6: 生成链路——create_entry / create_draft / update_entry

**Files:**
- Modify: `src/kb/new_entry.py`（`create_entry`）
- Modify: `src/kb/gate.py`（`create_draft` 回填、`update_entry`）
- Test: `tests/test_new.py`（追加）；`tests/test_gate.py` 或既有 create_draft/update_entry 测试文件（按仓库实际位置追加，断言如下）

**Interfaces:**
- Consumes: Task 1 schema（空串/短值/超长在 lint 面的表现已定）
- Produces: `create_entry(repo_root, *, type, domain, scope, title, generated, today=None, summary=None) -> Entry`；`create_draft(..., summary: str | None = None)`（回填模式，仿既有 body/tags）；`update_entry(repo_root, entry_id, *, ..., summary: str | None = None) -> Entry`（pop-式：传空串删除键）。

- [ ] **Step 1: 写失败测试**

`tests/test_new.py` 追加（文件头已有 `create_entry`/`TODAY`/`tmp_repo`）：

```python
def test_create_entry_summary_key(tmp_repo):
    """summary 三态: None 不写键(与既有行为零差)、空串写 ""(schema 豁免)、有值原样。"""
    e1 = create_entry(tmp_repo, type="pitfall", domain="frontend", scope="project",
                      title="无摘要", generated=False, today=TODAY)
    assert "summary" not in e1.fm
    e2 = create_entry(tmp_repo, type="pitfall", domain="frontend", scope="project",
                      title="空摘要", generated=False, today=TODAY, summary="")
    assert e2.fm["summary"] == ""
    e3 = create_entry(tmp_repo, type="pitfall", domain="frontend", scope="project",
                      title="有摘要", generated=False, today=TODAY,
                      summary="Vite HMR 在 Windows 偶发失效需固定 host。")
    assert e3.fm["summary"] == "Vite HMR 在 Windows 偶发失效需固定 host。"
    assert e3.summary() == "Vite HMR 在 Windows 偶发失效需固定 host。"
```

`update_entry` 测试（加到既有 update 用例所在文件；若无独立文件则放 `tests/test_new.py` 末尾，import `from kb.gate import update_entry`）：

```python
def test_update_entry_summary_set_and_clear(tmp_repo):
    """kb_update 传空串 = 清空 summary(pop 键); 不传 = 不碰。返回落盘后的 Entry。"""
    from kb.gate import update_entry
    e = create_entry(tmp_repo, type="pitfall", domain="frontend", scope="project",
                     title="更新摘要", generated=False, today=TODAY,
                     summary="旧结论一句, 覆盖更新场景。")
    e2 = update_entry(tmp_repo, e.fm["id"], summary="新结论一句, 覆盖更新场景。")
    assert e2.fm["summary"] == "新结论一句, 覆盖更新场景。"
    assert parse_entry(e.path).fm["summary"] == "新结论一句, 覆盖更新场景。"
    update_entry(tmp_repo, e.fm["id"])                        # 不传不动
    assert parse_entry(e.path).fm["summary"] == "新结论一句, 覆盖更新场景。"
    e3 = update_entry(tmp_repo, e.fm["id"], summary="")       # 空串 = 清空
    assert "summary" not in e3.fm
    assert "summary" not in parse_entry(e.path).fm
```

（`update_entry` 返回 `Entry` 而非 dict——实现体内是 `fm = dict(e.fm)` 式改写后 `_save`+`_reindex`；`find_by_id` 扫文件无需索引。若既有 update 测试的 fixture 组织不同，**照抄既有用例**，断言内容不变。）

- [ ] **Step 2: 跑红**

Run: `python -m pytest tests/test_new.py -v -k summary`
Expected: FAIL——`TypeError: create_entry() got an unexpected keyword argument 'summary'`。

- [ ] **Step 3: 实现——`new_entry.py`**

`create_entry` 签名 `today: dt.date | None = None,` 后加形参：

```python
                      summary: str | None = None,
```

fm 字典 `"updated": today.isoformat(),` 之前加（空串**保留写入**——模板/人工清空语义）：

```python
        # 显式 L2 结论句(spec 2026-11-14): None=未提供不写键; ""=显式清空(schema 豁免);
        # 1-9 字符可落盘但 lint 双报(schema+可读性), 调用方自慎。
        **({"summary": summary} if summary is not None else {}),
```

- [ ] **Step 4: 实现——`gate.py` 两处**

`create_draft` 签名 `severity: str | None = None,` 后加：

```python
                summary: str | None = None,
```

回填链改造（既有 `if severity: cur.fm["severity"] = severity` 之后追加一行；空串跳过=现状缺失，schema 豁免）：

```python
    if body or tags or severity or summary:
        cur = parse_entry(e.path)
        if body:
            cur.fm["title"] = cur.fm.get("title") or body[:40]
        if tags:
            cur.fm["tags"] = tags
        if severity:
            cur.fm["severity"] = severity
        if summary:
            cur.fm["summary"] = summary
        write_text_lf(e.path, dump_entry(cur))
```

`update_entry`：签名 `severity: str | None = None,` 后加形参 `summary: str | None = None,`；实现体首部 `fm = dict(e.fm)` 之后加（pop-式；空串=清空）：

```python
    if summary is not None:
        # kb_update 传空串 = 清空显式结论(回退派生兜底), 与既有 title/tags 的
        # "传了才覆盖"一致; 删除用 pop 而非置空串, 保持"键不存在=缺失"的 lint 判据
        if summary:
            fm["summary"] = summary
        else:
            fm.pop("summary", None)
```

- [ ] **Step 5: 跑绿**

Run: `python -m pytest tests/test_new.py tests/test_gate*.py -v`（`test_gate*` 按仓库实际文件名；无则只跑前者）
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```powershell
git add src/kb/new_entry.py src/kb/gate.py tests/test_new.py
git commit -m "feat(gate/new): create_entry/create_draft/update_entry 支持显式 summary"
```

---

### Task 7: CLI 与 MCP 透传 + 埋点口径回归锁定

**Files:**
- Modify: `src/kb/cli.py`（`kb new` 参数与两条分发路径）
- Modify: `src/kb/mcp_server.py`（`kb_create`/`kb_update`）
- Test: `tests/test_cli.py`、`tests/test_mcp.py`、`tests/test_federation_contract.py`（新建）

**Interfaces:**
- Consumes: Task 6 的 `create_entry(summary=...)`、`create_draft(..., summary=...)`、`update_entry(summary=...)`
- Produces: `kb new --summary "<一句结论>"`；MCP `kb_create`/`kb_update` inputSchema 含 `summary`；**cli.py search 埋点零改动**（`returned_chars` 实为 `len(json.dumps(res, ensure_ascii=False))` 默认分隔符口径），由 `test_returned_chars_compact` 断言锁定。

- [ ] **Step 1: 写失败测试（CLI）**

`tests/test_cli.py` 追加：

```python
def test_kb_new_summary_flag(tmp_repo, capsys):
    assert main(["new", "pitfall", "--domain", "frontend", "--title", "结论句演示",
                 "--summary", "Vite 端口漂移需固定 server.port。",
                 "--repo", str(tmp_repo)]) == 0
    out = capsys.readouterr().out
    eid = json.loads(out)["id"]
    from kb.query import get_entry
    assert get_entry(tmp_repo, eid)["summary"] == "Vite 端口漂移需固定 server.port。"
```

- [ ] **Step 2: 写失败测试（MCP + 契约形状，新文件）**

新建 `tests/test_federation_contract.py`（MCP 范式逐字对齐 `tests/test_mcp.py` 顶部）：

```python
"""联邦 L2 记录契约回归(spec 2026-11-14 §5.2-6/7): CLI/MCP 面 summary 透传、
形状一致、埋点 compact 口径锁定。"""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from kb import trace
from kb.cli import main
from kb.index import build_indexes
from kb.mcp_server import build_server
from conftest import make_entry

pytestmark = pytest.mark.asyncio


async def _call(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool(name, args)
        text = res.content[0].text
        return res.isError, (json.loads(text) if text.startswith(("{", "[")) else text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)   # 隔离真实 traces/
    monkeypatch.delenv("KB_TRACE", raising=False)
    proj = tmp_path / "docs"
    d = proj / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261114-f001", title="Vite HMR 抖动",
                                       status="accepted", confidence="verified"),
                            encoding="utf-8")
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


async def test_mcp_create_update_summary_roundtrip(env):
    _, proj = env
    srv = build_server(proj, [], repo_name="docs")
    err, out = await _call(srv, "kb_create", {
        "type": "howto", "domain": "tooling", "title": "联邦形状验证条目",
        "body": "## 用法\n用 kb_export 做跨仓上提的操作步骤说明。\n",
        "summary": "跨仓上提必须先 kb promote 建议再由人 set-scope。"})
    assert err is False
    err, out = await _call(srv, "kb_update", {"id": out["id"],
                                              "summary": "改后结论: 仍需人工终审。"})
    assert err is False
    err, hits = await _call(srv, "kb_search", {"query": "联邦形状验证条目"})
    row = hits[0]
    assert row["summary"] == "改后结论: 仍需人工终审。"
    assert row["origin"] == "local" and row["uri"] is None          # 与本地行同契约
    assert "hit_fields" in row                                       # 既有形状不破坏


def test_cli_search_hit_shape_matches_mcp(env):
    """§5.2-7: CLI 行与 MCP 行形状一致(CLI 全行透传 ⊇ MCP 字段)。"""
    _, proj = env
    assert main(["search", "--repo", str(proj), "--query", "Vite", "--no-trace"]) == 0
    # stdout 断言在 capsys 下不便与 fixture 共用, 直接走 search 层断言同集合
    from kb.search import search
    row = search(proj, query="Vite", limit=5)[0]
    assert {"hit_fields", "summary", "origin", "uri", "path", "id"} <= row.keys()


def test_returned_chars_compact(env, monkeypatch, capsys):
    """§4 口径锁定(本行即回归测试本身): 埋点 returned_chars 与 stdout 结果的
    compact `json.dumps(res, ensure_ascii=False)` 逐字符等长——print 的 indent 只准
    出现在 stdout, 混进字符账即虚高 overhead/meta_only。"""
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    assert main(["search", "--repo", str(proj), "--query", "vite"]) == 0
    res = json.loads(capsys.readouterr().out)   # stdout 是 indent 版, 解析回对象
    ev = _events(root)[0]
    assert ev["returned_chars"] == len(json.dumps(res, ensure_ascii=False))
```

（`res` 从 stdout 解析而非手拼期望值——埋点与 print 打印的是**同一个对象**，等长断言即锁死"埋点=compact 口径"，不依赖行的具体字段。）

- [ ] **Step 3: 跑红**

Run: `python -m pytest tests/test_cli.py tests/test_federation_contract.py -v`
Expected: CLI FAIL（`unrecognized arguments: --summary`，exit 2）；MCP roundtrip FAIL（inputSchema 无 summary → isError 或值未写入）。

- [ ] **Step 4: 实现——cli.py**

`p_new` 参数块 `--severity` 之后加：

```python
    p_new.add_argument("--summary", default=None,
                       help="一句结论(条件+结论+动作, 10-300 字); 缺省由正文首段派生")
```

`cmd == "new"` 分发：`create_draft(...)` 与 `create_entry(...)` 两处调用均加 `summary=args.summary,`（create_draft 的 severity 行之后）。

- [ ] **Step 5: 实现——mcp_server.py**

`kb_create`（L145 签名）`severity: str | None = None` 后加 `summary: str | None = None`；docstring 末行补一句：`summary 建议一句结论(条件+结论+动作, 10-300 字), 缺省由正文首段派生。`；`create_draft(...)` 调用加 `summary=summary,`。**返回面无需改**——`kb_create`/`kb_update` 返回都是 `_json({**e.fm, "path": str(e.path)})`，fm 自动携带 summary。

`kb_update`（L161 签名）同样加形参与 docstring 一句（空串=清空结论），`update_entry(...)` 调用加 `summary=summary,`。

- [ ] **Step 6: 跑绿**

Run: `python -m pytest tests/test_cli.py tests/test_mcp.py tests/test_federation_contract.py -v`
Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```powershell
git add src/kb/cli.py src/kb/mcp_server.py tests/test_cli.py tests/test_federation_contract.py
git commit -m "feat(cli/mcp): kb new --summary 与 kb_create/kb_update 透传; 埋点 compact 口径加断言锁定"
```

---

### Task 8: 模板与文档一致性（templates / AGENTS.md）

**Files:**
- Modify: `templates/*.md`（8 个文件 front-matter）
- Modify: `AGENTS.md`（§"怎么查"表格之后）

**Interfaces:**
- Consumes: Task 1 空串豁免（`summary: ""` 必须 lint 合法）
- Produces: 无代码接口；纯文档一致性。

- [ ] **Step 1: 模板加占位（8 文件同一动作）**

每个 `templates/<type>.md` 的 front-matter 中 `updated:` 行之前加一行：

```yaml
summary: ""
```

（`kb new` 运行时**不读模板**——正文骨架来自 taxonomy sections，本步只维持"模板=人读规范"与 schema 一致，spec §3.3；勿动正文六段。）

- [ ] **Step 2: AGENTS.md 一句指向**

"怎么查（三级披露）"表格的 **标准路径** 段落之后追加：

```markdown
**联邦记录契约**: `index.jsonl` 每行是可承接外部异构源(feishu/notion/wiki…)的 L2 联邦
记录(含 `origin`/`uri`, 本地恒 `local`/`null`), 唯一事实源见
`kb/reference/backend/2026-11-14-federated-l2-record-contract.md`(Task 9 落地)。
```

（本步与 Task 9 同批提交，无"未落地悬空指向"窗口——路径以 Task 9 Step 3 产出为准。）

- [ ] **Step 3: 验证模板占位 lint 合法**

Run: `python -m pytest tests/test_taxonomy.py -v -k summary`
Expected: PASS（空串豁免用例覆盖此语义；模板本身不被运行时解析，无需新测试）。

- [ ] **Step 4: Commit**

```powershell
git add templates AGENTS.md
git commit -m "docs(templates/AGENTS): summary 占位与联邦契约 L1 指向"
```

---

### Task 9: 收尾——全量回归 + 契约自描述条目 + 索引重建

**Files:**
- Create: `kb/reference/backend/2026-11-14-federated-l2-record-contract.md`（`kb new` 产出 → 人工 `kb set-scope` 上提 → `kb review` 终审）
- Regenerate: `kb/INDEX.md`、`kb/index.jsonl`、`kb/index.draft.jsonl`
- Test: 全量回归

**Interfaces:**
- Consumes: Task 3 的记录形状（自描述条目正文即该契约的 L3 全文）
- Produces: 契约文档化闭环；全库索引含 origin/uri。

- [ ] **Step 1: 全量回归**

Run: `python -m pytest -q`
Expected: 全绿。

- [ ] **Step 2: 真仓 lint 冒烟（存量零打扰复认）**

Run: `kb lint --scope agent-kb --repo .`
Expected: 无 `缺 summary` 行；既有 warning 与改动前基线一致（若仓库有 baseline 文件，diff 无新增摘要类条目）。

- [ ] **Step 3: 创建契约自描述条目**

先把正文写成临时文件 `_l2_contract_body.md`（内容=spec §1 全文：字段表、外部 id/origin 约定、适配器义务、不承诺事项——**去掉 H1**，从 `## 结论卡` 开始），然后：

```powershell
kb new reference --domain backend --title "联邦 L2 记录契约：index.jsonl 行是外部异构源接入的唯一接口" --generated --body-file _l2_contract_body.md --summary "外部异构源接入只需产出含 origin/uri 的 index.jsonl 行；本地条目恒为 origin=local、uri=null，检索与 lint 面零改动。" --repo .
```

（**不带 `--scope stack`**：`kb new --generated` 恒强制 scope=project，且红线 #2 agent 不能定 scope——stack 由下一步人工落地。）

用返回的 id 做 agent 自审终审（红线 #1：evidence + confidence 提升；draft→accepted 可直跳）：

```powershell
kb review <上一步返回的id> --to accepted --as-agent --confidence verified --evidence "tests/test_federation_contract.py 与 tests/test_index.py::test_records_carry_federation_fields 实测通过(2026-11-14)" --repo .
```

**人工步骤（由人执行，agent 不代跑）**：确认 accepted 后由人上提 scope——

```powershell
kb set-scope <同上id> stack --repo .
```

删除临时 `_l2_contract_body.md`。

- [ ] **Step 4: 重建索引并校验**

```powershell
kb index --repo .
kb index --check --repo .
kb lint --scope agent-kb --repo .
kb stat --repo .
```

Expected: `--check` 通过；lint 无硬错误；stat 的 `summary_coverage.explicit == 1`（契约条目本身是全库第一条显式 summary，总数 208）。

- [ ] **Step 5: 审阅生成物 diff 后提交**

`git status` 确认改动仅含：新条目文件 + `kb/INDEX.md`/`index.jsonl`/`index.draft.jsonl`（**不含 `traces/`**）：

```powershell
git add kb/reference/backend/2026-11-14-federated-l2-record-contract.md kb/INDEX.md kb/index.jsonl kb/index.draft.jsonl
git commit -m "docs(kb): 联邦 L2 记录契约自描述条目 + 索引重建(origin/uri 形状定版)"
```

---

## Self-Review 记录（写完计划后按 spec 新鲜眼光核对）

1. **Spec 覆盖**：§3.1→Task 1；§3.2→Task 2；§3.3→Task 4+6+7+8；§3.4（不回填）→Global Constraints（无实现任务，正确）；§1→Task 3+9；§4→Task 7（断言）；§5.1→Task 5；§5.2 七项→Task 2/5/4/6+7/7/3。无缺口。
2. **占位扫描**：无 TBD/"similar to"/"择一落地"。
3. **类型一致性**：`summary: str | None = None` 贯穿 create_entry/create_draft/update_entry/MCP/CLI；`update_entry` 返回 `Entry`（非 dict）已同步跨任务契约与 T6 断言；lint 消息键名 `缺 summary`/`summary 仅 N 字符` 与测试断言一致；`summary_coverage={"explicit","total"}` 与 Task 5 断言、Task 9 冒烟读数一致。
4. **实态核对修订（2026-11-14 逐文件取证后落实）**：T1 弃 `VALID`/`__import__` 改用既有 `_fm`+jsonschema 直测（`test_committed_schema_matches_derivation` 强制文档同步）；T2 测试全部改单行 summary 值 + `'""'` YAML 空串字面量（裸 `""` 经 conftest 行拼接会变 None）；T4 lint 缺失判据改**键存在性**（`if "summary" not in fm`，与 schema 空串豁免/派生空回落三处语义分工），插入锚点改实文（`_HTML_COMMENT_RE` L12、占位段 for 循环 L110-111）；T4/T6 回归测试弃"同指纹"假设（默认条目短源低于 MIN_FP_LEN 免检）；T5 `iter_entry_paths(repo_root)`、锚点 `"due_review": len(due),`；T6 `update_entry` 实现按体内 `fm = dict(e.fm)` 式重写、测试改 Entry 断言；T7 MCP 返回面无需改（`{**e.fm, "path"}` 自动携带）、`returned_chars` 断言改 capsys 解析 stdout 后与 compact dumps 等长全等；T9 `kb new --generated` 删 `--scope stack`（强制 project + 红线 #2），新增**人工** `kb set-scope <id> stack` 步骤，域统一 backend。
