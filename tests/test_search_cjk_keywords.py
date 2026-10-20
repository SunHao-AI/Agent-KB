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


def _rec(i, title, *, tags=(), summary="", keywords=None):
    r = {"id": f"kb-{i}", "title": title, "type": "pitfall", "domain": ["backend"],
         "tags": list(tags), "scope": "project", "status": "accepted",
         "confidence": "verified", "summary": summary,
         "path": f"kb/pitfall/backend/{i}.md", "updated": "2026-10-12", "repo": "web"}
    if keywords is not None:
        r["keywords"] = keywords
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
    body = ("# 标题行不重复收\n\n## 根因分析\n\n"
            "报 `PermissionError [WinError 32]` 时说明句柄未释放。\n\n"
            "```powershell\nclient.connect_db(host=$DB_HOST)\n```\n")
    kws = derive_keywords(body)
    # 围栏取完整标识符(client.connect_db 比拆开的 connect_db 更精确;
    # agent 查子串 connect_db 仍能经 find 命中), 语言标记 powershell 不收
    assert "client.connect_db" in kws and "$DB_HOST" in kws
    assert "powershell" not in kws
    assert "PermissionError" in kws                        # 行内反引号
    assert "根因分析" not in kws and "WinError" in kws     # H2 中文段名不进
    assert "标题行不重复收" not in " ".join(kws)           # H1 不进
    assert len(kws) <= 20
