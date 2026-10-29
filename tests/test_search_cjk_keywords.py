"""FR-3.3 CJK 2-gram 覆盖率匹配 / FR-3.4 正文 keywords 匹配面 的专项回归。

对应用户原始痛点: "必须字符严格匹配才行, 命中率较低"。
"""
import json

from kb.index import derive_keywords
from kb.search import search


def _mk(root, recs):
    d = root / "kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return root


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


# ---- FR-3.3 中文 2-gram 覆盖率 ------------------------------------------

def test_cjk_compound_query_hits(tmp_repo):
    """PRD 验收点: 「推流死锁」连写查询, 库文只有"推流线程死锁"也能命中。"""
    _mk(tmp_repo, [_rec(1, "推流线程死锁排查", summary="直播推流时线程池死锁")])
    rows = search(tmp_repo, query="推流死锁")
    assert [r["id"] for r in rows] == ["kb-1"]


def test_cjk_sparse_noise_rejected(tmp_repo):
    """覆盖率防线: 只沾 1/N 个 gram 的无关条目不放行。"""
    _mk(tmp_repo, [_rec(1, "推流参数配置", summary="码率与分辨率")])
    assert search(tmp_repo, query="推流死锁线程") == []


def test_cjk_short_token_unchanged(tmp_repo):
    """2 字 token(单 gram)行为与原整词匹配一致。"""
    _mk(tmp_repo, [_rec(1, "死锁排查"), _rec(2, "内存泄漏")])
    assert [r["id"] for r in search(tmp_repo, query="死锁")] == ["kb-1"]


def test_mixed_cjk_and_ascii_token(tmp_repo):
    """混合 token: vite 整词 + 中文段 2-gram 均须满足(AND 保持)。"""
    _mk(tmp_repo, [
        _rec(1, "vite 热更新失效", summary="开发服务器热更新不生效"),
        _rec(2, "webpack 热更新失效", summary="打包器热更新问题"),
    ])
    assert [r["id"] for r in search(tmp_repo, query="vite 热更新")] == ["kb-1"]


def test_ascii_wholeword_still_exact(tmp_repo):
    """西文不进 2-gram 通道: 错拼 permissionee 不因部分相似放行。"""
    _mk(tmp_repo, [_rec(1, "nonsense", keywords=["PermissionError"])])
    assert search(tmp_repo, query="permissionee") == []


# ---- FR-3.4 keywords 匹配面 ----------------------------------------------

def test_keywords_field_hit(tmp_repo):
    _mk(tmp_repo, [_rec(1, "文件句柄坑", keywords=["PermissionError", "EBUSY"])])
    rows = search(tmp_repo, query="permissionerror")
    assert [r["id"] for r in rows] == ["kb-1"]


def test_old_index_without_keywords_field_ok(tmp_repo):
    """老索引无 keywords 字段: 匹配面自动退化为三段, 不崩。"""
    _mk(tmp_repo, [_rec(1, "不含该字段的旧条目")])
    assert [r["id"] for r in search(tmp_repo, query="旧条目")] == ["kb-1"]


def test_keywords_rank_between_tags_and_summary(tmp_repo):
    _mk(tmp_repo, [
        _rec(1, "甲", summary="提了 EBUSY 但不权威"),      # summary 1
        _rec(2, "乙", keywords=["EBUSY"]),                  # keywords 2
        _rec(3, "丙 EBUSY"),                                # title 5
    ])
    rows = search(tmp_repo, query="EBUSY")
    assert [r["id"] for r in rows] == ["kb-3", "kb-2", "kb-1"]


# ---- FR-3.4 派生规则 -------------------------------------------------------

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


# ---- 按 H2 段分桶的配额(spec 4.1): 复刻线上故障 ----

def _kw_body_with_padded_first_section() -> str:
    """首段塞满标识符把旧的全局 cap=20 吃光, 次段的 zone/resolve 就永久不可见 ——
    线上 kb-20261012-64e8 追加 1400 字后 keywords 一字未变的机理。"""
    pad = "\n".join(f"报 `PadIdentifier{i:02d}Error` 时说明占位。" for i in range(30))
    return (
        "# 标题\n\n## 根因\n" + pad + "\n\n"
        "## 解决方案\n缺 `zone` 会报 `[emerg] resolving names at run time`,"
        " 需 `resolver` 与 `upstream-resolve` 配合 `keepalive`。\n"
    )


def test_later_section_keywords_survive_early_section_padding():
    """分桶后次段不再被首段挤光(线上条目追加 1400 字而 keywords 一字未变)."""
    from kb.entry import Entry

    e = Entry(fm={"id": "kb-1"}, body=_kw_body_with_padded_first_section(), path=None)
    kws = derive_keywords(e)
    assert "zone" in kws and "resolver" in kws       # 修复前: 首段吃满 cap=20, 必失
    assert "PadIdentifier00Error" in kws             # 首段词同样保留(非零和)


def test_per_section_quota_and_global_ceiling_bounds_total():
    """每段各得 8 词; 全局 64 是**安全阀**——第 9 个及以后的高密度段会被切掉.

    显式断言"哪些段被阀切掉"而不是含糊断言总数: 让该代价在测试里可见可讨论。
    六段式条目通常 ≤7 段, 实际语料极少触顶(实测 p50=31 / p90=55 / max=106)。
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
    同时抓住分桶逻辑写错导致的静默清零(比运行时防护更合适)。

    已知锋利边(有意): keywords 只收 ASCII 标识符, 一篇通篇中文零标识符的新条目会让本
    测试变红——那是"该条目检索面只剩 title+tags"的真信号, 应补 tags/标识符而非放宽断言。
    """
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
    recs = [json.loads(x) for x in
            (dst / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) > 50                                    # 语料确实进来了
    assert [r["id"] for r in recs if not r["keywords"]] == []


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
    line = [ln for ln in md.read_text(encoding="utf-8").splitlines()
            if ln.startswith("- [")][0]
    assert "段首句" not in line                              # 不进 INDEX.md
    assert line.endswith("首段摘要。")                        # 行尾仍是 summary, 未被推高
