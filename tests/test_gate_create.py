import datetime as dt
import pytest
from kb.gate import create_draft, DuplicateCandidate
from kb.index import build_indexes
from conftest import make_entry

BODY = ("## 背景 / 现象\n现象一。\n\n## 根因\n唯一根因文本内容, 涉及构建缓存失效的机制说明。"
        "\n\n## 解决方案\n改它。\n")

def _accepted_entry(tmp_repo, eid, title, root):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{eid}.md").write_text(
        make_entry(id=eid, title=title, status="accepted", confidence="verified")
        + f"\n## 根因\n{root}\n", encoding="utf-8")
    build_indexes(tmp_repo)

def test_create_draft_forced_invariants(tmp_repo):
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="新坑", body=BODY, today=dt.date(2026, 10, 13))
    assert (e.fm["status"], e.fm["confidence"], e.fm["scope"]) == ("draft", "speculative", "project")
    assert "唯一根因文本内容" in e.path.read_text(encoding="utf-8")

def test_dup_by_fingerprint_rejected(tmp_repo):
    _accepted_entry(tmp_repo, "kb-20261012-1111", "旧条目",
                    "唯一根因文本内容, 涉及构建缓存失效的机制说明。")
    with pytest.raises(DuplicateCandidate) as ei:
        create_draft(tmp_repo, type="pitfall", domain="frontend", title="换个名", body=BODY)
    assert ei.value.entries[0]["id"] == "kb-20261012-1111"

def test_dup_by_title_token_rejected(tmp_repo):
    _accepted_entry(tmp_repo, "kb-20261012-2222", "Vite HMR windows 失效", "无关根因甲。")
    with pytest.raises(DuplicateCandidate):
        create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="vite hmr 又失效", body="## 根因\n完全不相干的另一个根因说明。\n")

def test_no_hit_creates(tmp_repo):
    _accepted_entry(tmp_repo, "kb-20261012-3333", "无关主题", "无关根因甲。")
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="SQLAlchemy JSON 列原地改不落库", body="## 根因\n另一机制说明文本。\n")
    assert e.fm["status"] == "draft" and e.path.exists()

def test_tags_severity_applied(tmp_repo):
    e = create_draft(tmp_repo, type="pitfall", domain="frontend", title="带标签",
                     body=BODY + "\n## 参考\n无\n", tags=["vite"], severity="high")
    assert e.fm["tags"] == ["vite"] and e.fm["severity"] == "high"
