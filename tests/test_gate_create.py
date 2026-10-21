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


# --- B3: 单 token / 泛词命中不判重(2026-10-21 误报治理) ---
def test_dup_single_specific_token_not_rejected(tmp_repo):
    # 仅 1 个非泛词 token(vite)重合 → 不拒(旧规则 any 单 token 即拒, 误报主源)
    _accepted_entry(tmp_repo, "kb-20261012-6666", "Vite HMR 失效", "无关根因甲。")
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="vite 构建缓存击穿", body="## 根因\n另一机制说明文本内容。\n")
    assert e.fm["status"] == "draft" and e.path.exists()


def test_dup_stopword_token_not_rejected(tmp_repo):
    # 标题 token 全为泛词(windows/append)时 specific 为空 → 不判重;
    # 即历史误报场景: "windows 追加丢行" 曾被 chmod/TZ 等 windows 条目拦截
    _accepted_entry(tmp_repo, "kb-20261012-7777", "Windows chmod 不生效", "无关根因甲。")
    e = create_draft(tmp_repo, type="pitfall", domain="devops",
                     title="windows append 丢行", body="## 根因\n另一机制说明文本内容。\n")
    assert e.fm["status"] == "draft" and e.path.exists()

def test_no_hit_creates(tmp_repo):
    _accepted_entry(tmp_repo, "kb-20261012-3333", "无关主题", "无关根因甲。")
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="SQLAlchemy JSON 列原地改不落库", body="## 根因\n另一机制说明文本。\n")
    assert e.fm["status"] == "draft" and e.path.exists()

def test_tags_severity_applied(tmp_repo):
    e = create_draft(tmp_repo, type="pitfall", domain="frontend", title="带标签",
                     body=BODY + "\n## 参考\n无\n", tags=["vite"], severity="high")
    assert e.fm["tags"] == ["vite"] and e.fm["severity"] == "high"


# --- F5: body=None(仅标题查重路径)行为锁定 ---
def test_dup_title_hit_without_body_rejected(tmp_repo):
    # body=None 时无指纹可比, 查重退化为仅标题 token 命中, 命中仍须拒建
    _accepted_entry(tmp_repo, "kb-20261012-4444", "Vite HMR windows 失效", "无关根因甲。")
    with pytest.raises(DuplicateCandidate) as ei:
        create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="vite hmr 又失效", body=None)
    assert ei.value.entries[0]["id"] == "kb-20261012-4444"


def test_no_title_hit_without_body_creates(tmp_repo):
    # body=None 且标题不命中: 正常建 draft(正文为模板骨架, 非空 body 覆写)
    _accepted_entry(tmp_repo, "kb-20261012-5555", "无关主题", "无关根因甲。")
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="SQLAlchemy JSON 列原地改不落库", body=None)
    assert e.fm["status"] == "draft" and e.path.exists()
    text = e.path.read_text(encoding="utf-8")
    assert "## 根因" in text  # 模板骨架保留
