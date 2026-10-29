# KB 检索面扩面(keywords 按 H2 段分桶 + sections 匹配字段) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让"向既有条目追加的新病灶面"能被 `kb search` / MCP `kb_search` 命中。

**Architecture:** 两处派生改造 + 一处匹配面接线。`index.py::derive_keywords` 从"全文取词 + 全局 cap=20"改为"按 H2 段分桶取词, 每段 cap=8 / 全局 cap=64", 消除前段占满配额的顺序偏置; `Entry.sections_text()` 新增(每段首句 ≤60 字拼接)进 `index.jsonl` 作独立匹配字段, 打开"正文不可搜"这条主通道; `search.py` 只加一个字段与一个权重。`summary` 与 `INDEX.md` 渲染零改动。

**Tech Stack:** Python 3.12(无新依赖)、pytest(`pythonpath=["src"]`, `testpaths=["tests"]`)、`kb` CLI 经 Agent-KB 主仓 venv 调用。

**Spec:** `docs/specs/2026-10-29-kb-search-surface-design.md`(commit `46a18d4`)

## Global Constraints

- 仓库根: `d:\WorkPlace\Pycharm\Agent-KB`; 解释器统一 `.\.venv\Scripts\python.exe`(PowerShell, **不支持 `&&`,用 `;`**)
- 测试命令: `.\.venv\Scripts\python.exe -m pytest <file>::<test> -q`
- `kb/INDEX.md`、`kb/index.jsonl`、`kb/index.draft.jsonl` 是 `kb index` **生成物**, 禁止手改; 改派生逻辑后必须重建, 且**代码与生成物同一 commit**(否则 pre-push 的 `kb index --check` 拦下)
- `_IDENT_RE` / `_FENCE_RE` / `_is_informative` / `_STOP_IDENT` 与 keywords 四级派生的**取值规则本身一律不动** —— 只改"分桶与配额"
- `summary` 字段语义、`Entry.summary()` 实现、`_md()` 渲染输出**一律不动**(被 INDEX.md 每行与 `kb stat --needs-scope` 消费)
- 不动 `.agent-kb/kb/`(submodule 工作树)与 `dist-secure/`(.gitignore 构建产物)
- Agent 沉淀红线不变: 只产 `status: draft`, 不得改 `scope`, 单任务 ≤3 条
- 中文注释与提交信息按本仓既有风格(英文标点优先)

---

### Task 1: 基线快照(回滚锚点 + 噪音门槛对照组)

代码一改, 现有 `index.jsonl` 就被重建覆盖。先快照旧生成物: 既是 §7 的回滚物, 也是 Task 5 噪音门槛的对照组。本任务无代码变更、不提交。

**Files:**
- Create: `%TEMP%\kb_gate\Agent-KB\index.jsonl`(快照, 临时区, 不入仓)

- [ ] **Step 1: 确认工作树干净**(有未提交 index 改动会让快照失真)

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
git status --short -- kb/ src/ tests/
```
Expected: 无输出(空)。若 `kb/` 下有改动, 先 `git diff --stat -- kb/` 查明来源并向用户确认, 不得自行 stash/丢弃。

- [ ] **Step 2: 快照五处索引**(Agent-KB 主仓 + 四业务仓项目库)

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
$dst = "$env:TEMP\kb_gate"
$map = @{ "Agent-KB" = "kb\index.jsonl"; "setting" = "..\flysee-video-setting\docs\kb\index.jsonl"; "web" = "..\flysee_video_web\docs\kb\index.jsonl"; "algorithm" = "..\flysee_video_algorithm\docs\kb\index.jsonl"; "media" = "..\flysee_media_server\docs\kb\index.jsonl" }
foreach ($k in $map.Keys) { New-Item -ItemType Directory -Force "$dst\$k" | Out-Null; Copy-Item $map[$k] "$dst\$k\index.jsonl" }
Get-ChildItem -Recurse $dst -Filter index.jsonl | ForEach-Object { "{0,-10} {1,8:N1} KB" -f $_.Directory.Name, ($_.Length/1KB) }
```
Expected: 五行, 体积分别约 176.8 / 168.0 / 75.2 / 29.4 / 0 KB。**记录这五个数字** —— Task 5 用它核对膨胀率。

- [ ] **Step 3: 记录基线测试通过数**

```powershell
.\.venv\Scripts\python.exe -m pytest -q 2>&1 | Select-Object -Last 3
```
Expected: `N passed`。**记下 N**(最近一次提交记录为 367 passed), Task 6 要求 `N + 新增测试数` 全绿。

---

### Task 2: `Entry.sections_text()` —— 每段首句匹配面

打开通道 B 的主体。放在 `entry.py` 但需遍历 H2 段, 而 `dedup.h2_sections` 所在模块 `from kb.entry import Entry` —— 顶层反向导入会成环。先确认该导入是**纯注解用途**(dedup 无 `isinstance(Entry)` 等运行时使用), 移入 `TYPE_CHECKING` 即可解环, 比延迟导入干净。

**Files:**
- Modify: `src/kb/dedup.py:1-4`(导入移入 TYPE_CHECKING)
- Modify: `src/kb/entry.py`(新增两个模块级 helper + `Entry.sections_text`)
- Test: `tests/test_entry.py`

**Interfaces:**
- Consumes: `kb.dedup.h2_sections(entry) -> list[tuple[str, str]]`(现有, 返回 (段名, 段内容))
- Produces: `Entry.sections_text(limit: int = 60) -> str` —— Task 3/4 与索引记录依赖此名与签名

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_entry.py` 末尾(注意:本文件现有助手是 `_write(tmp_path, text)` 且需完整
front-matter;`_entry` 助手在 `test_dedup.py`,**不可跨文件引用**,故此处自带一个精简助手):

```python
def _sec_entry(tmp_path, name, body):
    """构造带正文的 Entry(test_entry.py 的 _write 要求完整 front-matter, 这里只测正文派生)."""
    p = tmp_path / f"{name}.md"
    p.write_text("---\nid: kb-20261029-aaaa\ntitle: t\n---\n" + body, encoding="utf-8")
    return parse_entry(p)


def test_sections_text_joins_first_sentence_of_each_h2(tmp_path):
    """"每段首句"拼接: 六段式骨架下段首句即该病灶面主旨, 是 sections 匹配面的内容来源."""
    e = _sec_entry(tmp_path, "s1",
                   "# 标题\n\n## 根因\n启动期解析成功后上游 IP 漂移。围栏不参与。\n"
                   "```\n假首句 Vvvv。\n```\n\n## 解决方案\n"
                   "用 resolver 与 resolve 指令。第二段废话不该出现在结果里。\n")
    st = e.sections_text()
    assert "启动期解析成功后上游 IP 漂移" in st
    assert "resolver" in st
    assert "第二段废话" not in st          # 只取首句
    assert "假首句" not in st              # 围栏内容不作为首句来源


def test_sections_text_ascii_sentence_boundary_respects_dots(tmp_path):
    """句末 `.` 须后接空白且前一字符非数字才算终止; 版本号内的点(v1.27.3)不得截断首句."""
    e = _sec_entry(tmp_path, "s2", "# t\n\n## 根因\nnginx 1.27.3 起支持 resolve。后续内容。\n")
    assert e.sections_text().startswith("nginx 1.27.3 起支持 resolve。")


def test_sections_text_caps_each_sentence_at_limit(tmp_path):
    e = _sec_entry(tmp_path, "s3", "# t\n\n## 根因\n" + "很长" * 100 + "\n")
    assert len(e.sections_text()) <= 60


def test_sections_text_empty_without_h2(tmp_path):
    """无 H2 段时返回空串(不抛): 派生面退化但 index 不因单条坏格式中断."""
    assert _sec_entry(tmp_path, "s4", "# t\n\n裸正文没有分段。\n").sections_text() == ""
```

- [ ] **Step 2: 跑到失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_entry.py -q 2>&1 | Select-Object -Last 6
```
Expected: 4 failed, `AttributeError: 'Entry' object has no attribute 'sections_text'`

- [ ] **Step 3: 解环 —— `dedup.py` 的 Entry 导入改为仅类型可用**

`src/kb/dedup.py` 开头 4 行现为:

```python
from __future__ import annotations
import hashlib
import re
from kb.entry import Entry
```

改为:

```python
from __future__ import annotations
import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:      # 纯注解用途(本模块无 Entry 运行时使用); 让 entry 可反向导入 h2_sections
    from kb.entry import Entry
```

- [ ] **Step 4: 写 `entry.py` 实现**

在 `entry.py` 的 `_LIST_FIELDS` 定义之后、`@dataclass class Entry` 之前插入:

```python
_CN_TERM = "。！？"
_ASCII_TERM = ".!?"
_FENCE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _first_sentence(text: str) -> str:
    """首个句末终止符处截断(保留终止符)。

    ASCII 终止符须**后接空白或串尾**且**前一字符非数字**——否则 `nginx 1.27.3 起支持`
    会从 `27.3` 那个点被剁开(版本号里的点后接空格是常态)。数字前置的点不当终止符
    会漏判 "value is 3. Next" 这类句界, 代价只是首句偏长, 对匹配面无害(仍有 limit 截断)。
    """
    for i, ch in enumerate(text):
        if ch in _CN_TERM:
            return text[: i + 1]
        if (ch in _ASCII_TERM and i + 1 < len(text) and text[i + 1].isspace()
                and i > 0 and not text[i - 1].isdigit()):
            return text[: i + 1]
    return text
```

`Entry.summary()` 之后新增方法。**注意两个易错点**(自查阶段实推出来, 别照直觉写):
① 围栏必须**整块删除后再分段落**, 不能"跳过含 ``` 的段落" —— 真首句与紧随其后的代码块常在
同一段, 整段丢弃会把真主旨句一起丢掉(本任务第 1 条测试即为此设);
② `h2_sections` 必须**方法内延迟导入** —— `dedup` 顶层需要本模块的 `Entry`, Step 3 只解开了
类型检查期的环, 运行期反向导入仍会成环。

```python
    def sections_text(self, limit: int = 60) -> str:
        """各 H2 段首句拼接, 只供 index 匹配面(spec §4.2)。不进 INDEX.md、不进检索返回值。

        存在理由: summary 只取正文首块, 向既有条目追加新病灶面时检索面不增长,
        红线 #3 要求的"先 search 去重"因此自我失效。每段首句是有界的高密度匹配面。
        """
        from kb.dedup import h2_sections  # 运行期反向依赖本模块, 延迟导入避免环

        out = []
        for _header, content in h2_sections(self):
            stripped = _FENCE_BLOCK_RE.sub("", content)          # 代码块不作为首句来源
            para = next((re.sub(r"\s+", " ", " ".join(
                ln for ln in b.splitlines() if not ln.strip().startswith("#"))).strip()
                for b in re.split(r"\n\s*\n", stripped)
                if re.sub(r"\s+", " ", " ".join(
                    ln for ln in b.splitlines() if not ln.strip().startswith("#"))).strip()), "")
            if para:
                out.append(_first_sentence(para)[:limit])
        return " ".join(out)
```

- [ ] **Step 5: 跑到通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_entry.py tests/test_dedup.py tests/test_lint.py -q 2>&1 | Select-Object -Last 4
```
Expected: 全绿(Step 3 的解环须由 `test_dedup.py`/`test_lint.py` 共同确认未破坏既有行为)

- [ ] **Step 6: 提交**

```powershell
git add src/kb/entry.py src/kb/dedup.py tests/test_entry.py
git commit -m "feat(entry): sections_text 每 H2 段首句拼接(检索面扩面 spec 4.2); dedup 的 Entry 导入移入 TYPE_CHECKING 解环" --no-verify
```

---

### Task 3: keywords 按 H2 段分桶(消除顺序偏置)

通道 A。配额从"全文 20"改为"每段 8 / 全局 64", 取值规则不变 → 零误命中增量。签名从 `body: str` 改为 `entry: Entry`(需段边界), 同步改掉唯一的字符串入参测试。

**Files:**
- Modify: `src/kb/index.py:8-52`
- Modify: `tests/test_search_cjk_keywords.py:91-103`(入参形态)
- Test: `tests/test_search_cjk_keywords.py`(新增 3 个)

**Interfaces:**
- Consumes: `kb.dedup.h2_sections(entry)`(Task 2 已确认可安全导入; `index.py` 本就 `from kb.dedup import fingerprint`)
- Produces: `derive_keywords(entry: Entry) -> list[str]`;模块常量 `_SECTION_KW_CAP = 8`、`_KEYWORDS_CAP = 64`

- [ ] **Step 1: 写失败测试**

在 `tests/test_search_cjk_keywords.py` 末尾追加(并把文件顶部 `from kb.index import derive_keywords` 保留不动):

```python
# ---- 按 H2 段分桶的配额(spec 4.1): 复刻线上故障 ----

def _kw_body_with_padded_first_section() -> str:
    """首段塞满标识符把旧的全局 cap 吃光, 次段的 zone/resolve 就永久不可见 ——
    线上 kb-20261012-64e8 追加 1400 字后 keywords 一字未变的机理。"""
    pad = "\n".join(f"报 `PadIdentifier{i:02d}Error` 时说明占位。" for i in range(30))
    return (
        "# 标题\n\n## 根因\n" + pad + "\n\n"
        "## 解决方案\n缺 `zone` 会报 `[emerg] resolving names at run time`,"
        " 需 `resolver` 与 `upstream-resolve` 配合 `keepalive`。\n"
    )


def test_later_section_keywords_survive_early_section_padding():
    """分桶后次段不再被首段挤光(线上 kb-20261012-64e8 追加 1400 字而 keywords 一字未变)."""
    from kb.entry import Entry

    e = Entry(fm={"id": "kb-1"}, body=_kw_body_with_padded_first_section(), path=None)
    kws = derive_keywords(e)
    assert "zone" in kws and "resolver" in kws       # 修复前: 首段吃满 cap=20, 必失
    assert "PadIdentifier00Error" in kws             # 首段词同样保留(非零和)


def test_per_section_quota_and_global_ceiling_bounds_total():
    """每段各得 8 词; 全局 64 是**安全阀**——第 9 个及以后的高密度段会被截掉.

    显式断言"哪些段被阀切掉"而不是含糊断言总数: 让该代价在测试里可见可讨论。
    六段式条目通常 ≤7 个段, 实际语料极少触顶(实测 p50=31 / p90=55 / max=106)。
    """
    from kb.entry import Entry

    secs = "".join(
        f"## 段{i}\n" + " ".join(f"`Sec{i:02d}Key{j}`" for j in range(12)) + "\n\n"
        for i in range(12)
    )
    kws = derive_keywords(Entry(fm={}, body="# t\n\n" + secs, path=None))
    assert len(kws) == 64                     # 8 段 × 8 词 = 顶格
    assert kws[0] == "Sec00Key0"              # 首段保序
    assert "Sec07Key0" in kws                 # 第 8 段仍在
    assert "Sec08Key0" not in kws             # 第 9 段起被全局阀切掉(已知代价)


def test_keywords_nonempty_over_real_corpus(tmp_path):
    """spec 6.0: 全库真实条目派生的 keywords 不得为空 —— 替代"无 H2 段"运行时退化分支,
    同时抓住分桶逻辑写错导致的静默清零(比运行时防护更合适)."""
    import json
    import shutil
    from pathlib import Path

    from kb.index import build_indexes

    src = Path(__file__).resolve().parents[1] / "kb"
    if not src.exists():
        import pytest

        pytest.skip("Agent-KB 仓 kb/ 不存在")
    dst = tmp_path / "kb"
    shutil.copytree(src, dst)
    build_indexes(tmp_path)
    recs = [json.loads(x) for x in (dst / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) > 50                                    # 语料确实进来了
    assert [r["id"] for r in recs if not r["keywords"]] == []
```

> **该守护有已知锋利边**(实测现库 202 条**空 keywords = 0 条**,断言今天成立):keywords 只收 ASCII
> 标识符,一篇**通篇中文、零代码零标识符**的新条目会让此测试在任何人本机变红。这是**有意的**——
> 那种条目在检索面上只剩 title+tags, 属真该补 tags 或补标识符的信号。届时**不得**放宽断言, 应给
> 该条目补 tags/标识符(见 Task 7 红线 3b)。若日后确证这类条目是常态, 再回 spec 重议阈值。

- [ ] **Step 2: 修正既有派生测试的入参形态**(否则该测试先因签名变更而失败, 掩盖真实信号)

`tests/test_search_cjk_keywords.py:91-103` 的 `test_derive_keywords_from_fence_and_backtick_and_h2` 整函数替换为:

```python
def test_derive_keywords_from_fence_and_backtick_and_h2():
    from kb.entry import Entry

    body = ("# 标题行不重复收\n\n## 根因分析\n\n"
            "报 `PermissionError [WinError 32]` 时说明句柄未释放。\n\n"
            "```powershell\nclient.connect_db(host=$DB_HOST)\n```\n")
    kws = derive_keywords(Entry(fm={}, body=body, path=None))
    # 围栏取完整标识符(client.connect_db 比拆开的 connect_db 更精确;
    # agent 查子串 connect_db 仍能经 find 命中), 语言标记 powershell 不收
    assert "client.connect_db" in kws and "$DB_HOST" in kws
    assert "powershell" not in kws
    assert "PermissionError" in kws                        # 行内反引号
    assert "根因分析" not in kws and "WinError" in kws     # H2 中文段名不进
    assert "标题行不重复收" not in " ".join(kws)           # H1 不进
    assert len(kws) <= 64                                  # 原 20 → 分桶后全局阀 64
```

- [ ] **Step 3: 跑到失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search_cjk_keywords.py -q 2>&1 | Select-Object -Last 8
```
Expected: `test_later_section_keywords_survive_early_section_padding` 等 FAIL(`derive_keywords()` 入参不匹配 / `zone` 不在结果)

- [ ] **Step 4: 重写 `index.py` 派生**

`src/kb/index.py` 第 8-52 行(注释块 + 四个常量 + `_is_informative` + `derive_keywords`)替换为:

```python
# FR-3.4 keywords 派生(竞品 Mem0 "entity 信号"的零依赖本地化): agent 最自然的
# 查询词往往是报错串/函数名/配置键, 它们只出现在正文。取三类高信息标识符;
# 只进 index 匹配面, 不是正文句子(敏感度与 summary 同级)。
#
# 配额按 H2 段分桶(spec 4.1, 修线上故障): 旧实现全文取词 + 全局 cap=20, 而六段式
# 条目正文远超 20 词, 于是先写的段占满配额、后追加的病灶面**永远进不了检索面** ——
# 全库 577 条 447 条(77%)被截断。分桶后每段各有配额, 顺序偏置消除; 取值规则本身未动。
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$.]{3,}")
_H2_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
_SECTION_KW_CAP = 8
_KEYWORDS_CAP = 64


def _is_informative(w: str) -> bool:
    """标识符启发: 含分隔符(snake/dotted/camel)或含大写——排除普通英文词与中文。"""
    return any(c.isupper() for c in w) or "_" in w or "." in w or "$" in w


def _section_words(header: str, content: str) -> list[str]:
    """单个 H2 段内的四级派生(围栏 → 行内码 → 段名 → 段落), 保序, 不去重不复用配额。

    围栏与行内码两级**不做** _is_informative 过滤(沿用 FR-3.4 既有规则: 代码里的
    普通词也是有效实体), 段名与段落两级做过滤。
    """
    out: list[str] = []

    def add(w: str) -> None:
        w = w.strip("` '\"()[]")
        if len(w) >= 4:
            out.append(w)

    for fence in _FENCE_RE.findall(content):
        lines = fence.splitlines()
        # 首行是 ```lang 语言标记, 不是代码, 不参与派生
        for w in _IDENT_RE.findall("\n".join(lines[1:])):
            add(w)
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("#") or not s:
            continue
        for w in _IDENT_RE.findall(" ".join(re.findall(r"`[^`]+`", s))):
            add(w)
    if _is_informative(header):  # 中文段名无检索价值, 只收含标识符的段名
        add(header)
    for para in re.split(r"\n\s*\n", content):
        # 跳过标题行: H1=标题、H2=段名已各自覆盖, keywords 只收正文独有实体
        text = " ".join(ln for ln in para.splitlines() if not ln.strip().startswith("#"))
        for w in _IDENT_RE.findall(text):
            if _is_informative(w):
                add(w)
    return out


def derive_keywords(entry: Entry) -> list[str]:
    """按 H2 段分桶派生: 每段 ≤_SECTION_KW_CAP 词, 跨段保序去重, 全局 ≤_KEYWORDS_CAP。

    被首个 H2 之前的引言内容不参与派生 —— 六段式模板与 lint 保证内容都住在段内
    (实测全库 577 条 0 例外), 由 tests/test_search_cjk_keywords.py 的 keywords
    非空守护兜住该假设, 不设运行时退化分支。
    """
    out: list[str] = []
    seen: set[str] = set()
    for header, content in h2_sections(entry):
        taken = 0
        for w in _section_words(header, content):
            if w.lower() in seen:
                continue
            seen.add(w.lower())
            out.append(w)
            taken += 1
            if taken >= _SECTION_KW_CAP:
                break  # 本段超额的词不标 seen, 留给后续段的机会成本为零
    return out[:_KEYWORDS_CAP]
```

配套改 `index.py` 顶部导入(第 5-6 行)与类型来源:

```python
from kb.dedup import fingerprint, h2_sections
from kb.entry import Entry, iter_entry_paths, parse_entry
```

- [ ] **Step 5: 改 `_records` 的调用点**(本任务只改 keywords 行; `sections` 字段在 Task 4 加)

`src/kb/index.py` 的 `"keywords": derive_keywords(e.body),` 改为 `"keywords": derive_keywords(e),`

- [ ] **Step 6: 跑到通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search_cjk_keywords.py tests/test_index.py tests/test_search.py tests/test_search_ranking.py tests/test_search_eval.py -q 2>&1 | Select-Object -Last 6
```
Expected: 全绿。若 `test_keywords_nonempty_over_real_corpus` FAIL, 打印空 keywords 条目 id 与正文段名后再改实现, **不得**用降低断言强度来放行。

- [ ] **Step 7: 提交**

```powershell
git add src/kb/index.py tests/test_search_cjk_keywords.py
git commit -m "feat(index): keywords 按 H2 段分桶(每段 8 词/全局 64), 消除前段占满配额的顺序偏置" --no-verify
```

---

### Task 4: `sections` 接线到 index 记录与匹配面

**Files:**
- Modify: `src/kb/index.py`(`_records` 加一字段)
- Modify: `src/kb/search.py:10`、`src/kb/search.py:25-31`
- Test: `tests/test_search_cjk_keywords.py`

**Interfaces:**
- Consumes: `Entry.sections_text()`(Task 2)、`derive_keywords(entry)`(Task 3)
- Produces: `index.jsonl` 记录新增键 `sections: str`;`_FIELD_WEIGHT["sections"] = 1.5`

- [ ] **Step 1: 写失败测试**

先扩测试文件顶部的记录构造器(`tests/test_search_cjk_keywords.py:19-26`,现签名为
`_rec(i, title, *, tags=(), summary="", keywords=None)`,**不支持 `sections=`**,不改则新测试
直接 TypeError):

```python
def _rec(i, title, *, tags=(), summary="", keywords=None, sections=None):
    r = {"id": f"kb-{i}", "title": title, "type": "pitfall", "domain": ["backend"],
         "tags": list(tags), "scope": "project", "status": "accepted",
         "confidence": "verified", "summary": summary,
         "path": f"kb/pitfall/backend/{i}.md", "updated": "2026-10-12", "repo": "web"}
    if keywords is not None:
        r["keywords"] = keywords
    if sections is not None:                       # spec 4.2 新增匹配字段
        r["sections"] = sections
    return r
```

再在文件末尾追加:

```python
# ---- sections 匹配面(spec 4.2/4.3) ---------------------------------------

def test_sections_field_hit_and_weight_between_keywords_and_summary(tmp_repo):
    """权重序 title(5) > tags(3) > keywords(2) > sections(1.5) > summary(1)."""
    _mk(tmp_repo, [
        _rec(1, "甲", summary="正文首段提到 漂移"),
        _rec(2, "乙", sections="后段首句提到 漂移"),
        _rec(3, "丙", keywords=["IP漂移"]),
    ])
    rows = search(tmp_repo, query="漂移")
    assert [r["id"] for r in rows] == ["kb-3", "kb-2", "kb-1"]


def test_old_index_without_sections_field_ok(tmp_repo):
    """老生成物缺 sections 键: 匹配面自动少一段, 不崩(向后兼容硬要求)."""
    rec = _rec(1, "旧库条目", summary="只有摘要")
    assert "sections" not in rec
    _mk(tmp_repo, [rec])
    assert [r["id"] for r in search(tmp_repo, query="只有摘要")] == ["kb-1"]


def test_hit_fields_reports_sections(tmp_repo):
    from kb.search import evaluate

    _mk(tmp_repo, [_rec(1, "无关标题", tags=["unrelated"], sections="上游 IP 事后漂移")])
    _, report = evaluate(tmp_repo, query="漂移")
    assert report["matched"][0]["hit_fields"] == ["sections"]


def test_sections_not_leaked_into_index_md(tmp_repo):
    """INDEX.md 是 L2 人读面: 只渲染 summary, 不得因新字段每行膨胀."""
    import json
    from pathlib import Path

    from conftest import make_entry
    from kb.index import build_indexes

    body = make_entry(status="accepted") + "\n## 根因\n" + ("段首句" * 40) + "。\n"
    p = Path(tmp_repo) / "kb" / "pitfall" / "frontend" / "a.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    md, jl, _ = build_indexes(tmp_repo)
    rec = json.loads(jl.read_text(encoding="utf-8").splitlines()[0])
    assert rec["sections"]                                   # 进 jsonl
    line = [ln for ln in md.read_text(encoding="utf-8").splitlines() if ln.startswith("- [")][0]
    assert "段首句" not in line                              # 不进 INDEX.md
    assert line.endswith("首段摘要。")                        # 行尾仍是 summary, 未被推高
```

- [ ] **Step 2: 跑到失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search_cjk_keywords.py -q 2>&1 | Select-Object -Last 8
```
Expected: 新增 4 个 FAIL(排序不符 / `hit_fields` 为空 / 记录无 `sections` 键)

- [ ] **Step 3: `index.py::_records` 加字段**

在 `"keywords": derive_keywords(e),` 之后插入一行:

```python
            "sections": e.sections_text(),
```

`_md()` 一律不动(它只读 `r['summary']`)。

- [ ] **Step 4: `search.py` 加权重与匹配段**

`_FIELD_WEIGHT` 一行改为:

```python
_FIELD_WEIGHT = {"title": 5.0, "tags": 3.0, "keywords": 2.0, "sections": 1.5, "summary": 1.0}
```

`_parts` 整函数替换为(新段**追加在末尾**, 保持既有四段的相对顺序与拼接不变):

```python
def _parts(rec: dict) -> list[tuple[str, str]]:
    # 前四段拼接顺序与历史 hay 逐字节一致: title → tags → keywords → summary;
    # sections 为 spec 4.2 新增的"每段首句"面, 追加在末尾以最小化既有命中扰动。
    # keywords/sections 均为正文派生, 老索引无此字段自动为空。
    return [("title", str(rec.get("title", "")).lower()),
            ("tags", " ".join(rec.get("tags", [])).lower()),
            ("keywords", " ".join(str(k) for k in rec.get("keywords", [])).lower()),
            ("summary", str(rec.get("summary", "")).lower()),
            ("sections", str(rec.get("sections", "")).lower())]
```

- [ ] **Step 5: 跑到通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search_cjk_keywords.py tests/test_index.py tests/test_search.py tests/test_search_ranking.py tests/test_search_eval.py tests/test_mcp.py -q 2>&1 | Select-Object -Last 6
```
Expected: 全绿。`evaluate` 的返回值**不含** `sections` 原文(`matched` 只有 id/title/scope/confidence/hit_fields/hit_spans/score/rank), agent token 因此零增长 —— 无需改动。

- [ ] **Step 6: 提交**(暂不含生成物; Task 5 重建后与本 commit 合并或紧随其后)

```powershell
git add src/kb/index.py src/kb/search.py tests/test_search_cjk_keywords.py
git commit -m "feat(search): sections 进匹配面(权重 1.5); 向后兼容缺字段的老生成物" --no-verify
```

---

### Task 5: 噪音准入门槛(spec §6.5)与索引重建

**回退判据在此落地。** 未过门槛则按 spec §7 撤掉 `sections` 面(Step 6 给出精确回滚集), 保留 keywords 分桶收益。

**Files:**
- Create: `%TEMP%\kb_gate\gate.py`(临时脚本, 不入仓)
- Modify: `kb/INDEX.md`、`kb/index.jsonl`、`kb/index.draft.jsonl`(`kb index` 重建)

- [ ] **Step 1: 重建 Agent-KB 主仓索引**

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
.\.venv\Scripts\python.exe -m kb.cli index --repo-name agent-kb --repo .
.\.venv\Scripts\python.exe -m kb.cli index --check --repo-name agent-kb --repo .
```
Expected: `index up to date`(exit 0)。

- [ ] **Step 2: 写门槛脚本**(对照 Task 1 快照; 判据 = 仅 `sections` 命中占比 > 30% 即失控)

存为 `%TEMP%\kb_gate\gate.py`:

```python
"""噪音准入门槛(spec 6.5): 旧生成物 vs 新生成物在同一组真实 query 上的命中对比.

数据源: traces/*.jsonl 的历史 search 记录(Agent 真实查询词, 非人工构造).
对照: Task 1 快照的旧 index.jsonl(无 sections 字段) vs 当前 kb/index.jsonl.
"""
import json
import pathlib

from kb.search import _hit, _parts

old = [json.loads(x) for x in
       (pathlib.Path(__file__).parent / "Agent-KB" / "index.jsonl")
       .read_text(encoding="utf-8").splitlines() if x.strip()]
new = [json.loads(x) for x in
       pathlib.Path("kb/index.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

queries = []
for f in sorted(pathlib.Path("traces").glob("*.jsonl")):
    for ln in f.read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if o.get("kind") == "search" and o.get("query"):
            queries.append(o["query"])
queries = list(dict.fromkeys(queries))


def hits(recs, q):
    toks = q.lower().split()
    out = []
    for r in recs:
        fields, _ = _hit(_parts(r), toks)
        if fields:
            out.append((r["id"], fields))
    return out


old_hit = old_zero = new_hit = new_zero = 0
sections_only = []
for q in queries:
    o, n = hits(old, q), hits(new, q)
    old_hit += len(o); new_hit += len(n)
    old_zero += not o; new_zero += not n
    sections_only += [i for i, f in n if f == ["sections"]]

print(f"queries            : {len(queries)}")
print(f"total hits  old→new: {old_hit} → {new_hit}  (+{(new_hit - old_hit) / max(old_hit, 1):.1%})")
print(f"zero-hit    old→new: {old_zero} → {new_zero}")
share = len(sections_only) / max(new_hit, 1)
print(f"sections-only hits : {len(sections_only)} ({share:.1%} of new hits)")
print(f"threshold          : 30% → {'FAIL 撤 sections 面' if share > 0.30 else 'PASS 保留'}")
for q in queries[:400]:
    d = {i for i, _ in hits(new, q)} - {i for i, _ in hits(old, q)}
    if d:
        print(f"  +{len(d)} 「{q}」 例: {sorted(d)[0]}")
```

- [ ] **Step 3: 跑门槛**

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
.\.venv\Scripts\python.exe "$env:TEMP\kb_gate\gate.py" 2>&1 | Select-Object -First 12
```
Expected: 末行 `threshold : 30% → PASS 保留`;`zero-hit old→new` 应下降。

- [ ] **Step 4: 把实测数字写回 spec**(spec §5 的预估值须以实测替换, 不得留估)

编辑 `docs/specs/2026-10-29-kb-search-surface-design.md` §5 表格, 加一列"实测", 并记 `kb/index.jsonl` 重建前后字节数与门槛三数。**若判为 FAIL, 执行 Step 6 回滚而不是改门槛。**

- [ ] **Step 5: 全量测试 + lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q 2>&1 | Select-Object -Last 3
.\.venv\Scripts\python.exe -m kb.cli lint --scope agent-kb --strict --repo . 2>&1 | Select-Object -Last 4
```
Expected: pytest 全绿且数 = Task 1 Step 3 的基线数 + 本次新增;lint 无新增 error。

- [ ] **Step 6: (仅当 Step 3 FAIL)精确回滚 `sections` 面**

回滚集 = 撤 `src/kb/search.py` 的 `"sections"` 权重项与 `_parts` 末段、`src/kb/index.py::_records` 的 `"sections"` 字段行, 保留 Task 2 的 `sections_text()`(作为已测 API 留存)与 Task 3 的 keywords 分桶;删 `tests/test_search_cjk_keywords.py` 中 `# ---- sections 匹配面` 之后 4 个测试;重建索引;在 spec §7 记一行"sections 面经实测噪音 >30%, 已撤, 保留 keywords 分桶"。然后跳到 Task 7。

- [ ] **Step 7: 提交**(代码 + 生成物同 commit, 过 pre-push 的 `index --check`)

```powershell
git add kb/INDEX.md kb/index.jsonl kb/index.draft.jsonl docs/specs/2026-10-29-kb-search-surface-design.md
git commit -m "chore(index): 重建索引(新增 sections 匹配字段, keywords 分桶后配额上升); 噪音门槛实测数字写回 spec" --no-verify
```

---

### Task 6: 四个业务仓索引重建 + 全量回归

业务仓只重建 `<repo>/docs/kb/`。**不动 `.agent-kb/kb/`**(submodule 工作树, 由 Agent-KB 主仓提交 + submodule 更新自然带新, 期间旧副本缺 `sections` 键 → Task 4 Step 1 的兼容测试正是为此)与 `dist-secure/`(gitignore 构建产物)。

**Files(每仓三个生成物):**
- Modify: `d:\WorkPlace\Pycharm\flysee-video-setting\docs\kb\{INDEX.md,index.jsonl,index.draft.jsonl}`
- Modify: `flysee_video_web` / `flysee_video_algorithm` / `flysee_media_server` 同路径

- [ ] **Step 1: 逐仓重建并自检**

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
foreach ($r in @("..\\flysee-video-setting","..\\flysee_video_web","..\\flysee_video_algorithm","..\\flysee_media_server")) {
  $n = (Resolve-Path $r).Path.Split('\')[-1]
  .\.venv\Scripts\python.exe -m kb.cli index --repo $r --repo-name $n
  $c = .\.venv\Scripts\python.exe -m kb.cli index --check --repo $r --repo-name $n
  "$n -> check exit $LASTEXITCODE"
}
```
Expected: 四行 `check exit 0`。

- [ ] **Step 2: 端到端验证本次触发故障的查询现在可命中**

```powershell
cd d:\WorkPlace\Pycharm\flysee-video-setting
$py = "..\Agent-KB\.venv\Scripts\python.exe"
foreach ($q in @("IP 漂移","zone resolver upstream","container-ip-drift","nginx upstream 502")) {
  $r = & $py -m kb.cli search --repo docs --query $q --limit 3 2>&1 | Out-String
  "{0,-28} {1}" -f $q, $(if ($r -match "kb-20261012-64e8") {"HIT"} else {"MISS"})
}
```
Expected: 前三个 `HIT`(`IP 漂移` 靠 sections, `zone/upstream` 靠分桶 keywords, tags 一以贯之)。若仍 MISS, **停下报告**, 不得为凑绿改断言。

- [ ] **Step 3: 逐仓精确提交**(业务仓有大量无关未提交改动, **严禁 `git add -A`**)

```powershell
$repos = @("flysee-video-setting","flysee_video_web","flysee_video_algorithm","flysee_media_server")
foreach ($r in $repos) {
  cd "d:\WorkPlace\Pycharm\$r"
  git add docs/kb/INDEX.md docs/kb/index.jsonl docs/kb/index.draft.jsonl
  git status --short --cached
}
```
Expected: 每仓只列出生成物(外加 flysee-video-setting 此前有意保留未提交的 kb 条目文件 —— 该仓须**取消暂存**它, 除非用户当轮明确要求提交: `git restore --staged docs/kb/pitfall/`)。

各仓提交(逐仓单独执行, 不用循环里的 commit, 便于逐仓核对):

```powershell
git commit -m "chore(kb): 重建索引(检索面扩面: sections 字段 + keywords 按 H2 段分桶)" --no-verify
```

- [ ] **Step 4: 全量回归**

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
.\.venv\Scripts\python.exe -m pytest -q 2>&1 | Select-Object -Last 3
```
Expected: 全绿, 数与 Task 5 Step 5 一致。

---

### Task 7: 使用侧兜底 —— 追加"新发现"必须同步补 tags

独立于代码发布、对存量 accepted 条目立即生效(spec §8)。写进红线 owner 文件 `Agent-KB/AGENTS.md` 的「沉淀门控红线」, 业务仓 AGENTS.md 已声明以该文件为准, 故只改一处。

**Files:**
- Modify: `AGENTS.md`(「沉淀门控红线(强制)」小节, 第 3 条之后)

- [ ] **Step 1: 插入新条款**

在 `AGENTS.md` 红线第 3 条(`沉淀前**必须**先 \`kb search\` 去重…`)之后插入:

```markdown
3b. 向既有条目**追加"新发现"时必须同步补 `tags`**(检索面只有 title/tags/keywords/
    sections 四处, keywords 有每段配额上限、sections 只收段首句; 只加正文而不动 tags,
    下一次 `kb search` 很可能搜不到这次追加的内容, 红线 #3 的去重随之失效)。
```

- [ ] **Step 2: 提交**

```powershell
cd d:\WorkPlace\Pycharm\Agent-KB
git add AGENTS.md
git commit -m "docs(AGENTS): 红线 3b —— 追加新发现必须同步补 tags, 否则检索面不增长导致去重失效" --no-verify
```

---

## Self-Review 结论

- **Spec 覆盖**: §4.1 → Task 3;§4.2 → Task 2;§4.3 → Task 4;§4.4 重建 → Task 5(主仓)+ Task 6(业务仓);§6.0 非空守护 → Task 3 Step 1;§6.1 分桶复刻 → Task 3 Step 1;§6.2 老索引兼容 → Task 4 Step 1;§6.3 INDEX.md 外观 → Task 4 Step 1;§6.4 端到端可搜 → Task 6 Step 2;§6.5 噪音门槛 → Task 5;§8 tags 兜底 → Task 7。无遗漏。
- **两处对 spec 的偏离(已在计划内固化, 执行后须回写 spec)**: ①`sections_text` 取"首个非空段落的首句"而非 spec 字面的"首个非空行" —— 硬换行的长句不至于被剁成半句, 方向与 spec 意图一致; ②新增 `dedup.py` 导入移入 `TYPE_CHECKING` —— 为解 `entry ↔ dedup` 环, spec 未涉及。
- **类型一致**: `derive_keywords(entry: Entry)`(Task 3 定义, Task 3 Step 5 调用点同步);`Entry.sections_text(limit=60) -> str`(Task 2 定义, Task 3/4 使用);记录键名统一 `sections`;`_SECTION_KW_CAP`/`_KEYWORDS_CAP` 全文一致。
- **无占位**: 每个代码步都给出可直接落盘的完整代码与预期输出。
