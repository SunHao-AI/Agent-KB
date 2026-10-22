import datetime as dt
import re
from kb.new_entry import new_id, slug, create_entry

TODAY = dt.date(2026, 10, 12)


def test_new_id_format():
    assert re.match(r"^kb-20261012-[0-9a-f]{4}$", new_id(TODAY))


def test_slug_kebab_with_date_prefix():
    assert slug("Vite HMR 在 Windows", TODAY) == "2026-10-12-vite-hmr-windows"


def test_create_entry_writes_path_and_frontmatter(tmp_repo):
    e = create_entry(tmp_repo, type="pitfall", domain="frontend",
                     scope="stack", title="Vite HMR", generated=True, today=TODAY)
    assert e.path.exists()
    assert e.fm["id"].startswith("kb-20261012-") and e.fm["type"] == "pitfall"
    assert e.fm["status"] == "draft" and e.fm["confidence"] == "speculative"
    assert e.path.parent.parts[-2:] == ("pitfall", "frontend")


def test_generated_never_accepted(tmp_repo):
    e = create_entry(tmp_repo, type="howto", domain="tooling",
                     scope="project", title="x", generated=True, today=TODAY)
    assert e.fm["status"] != "accepted"


def test_title_with_colon_space_roundtrip(tmp_repo):
    title = "注意: 这是一个坑"
    e = create_entry(tmp_repo, type="pitfall", domain="frontend",
                     scope="stack", title=title, generated=False, today=TODAY)
    assert e.fm["title"] == title


def test_title_with_hash_space_not_truncated(tmp_repo):
    title = "Bug #1 修复 #2 方案"
    e = create_entry(tmp_repo, type="pitfall", domain="backend",
                     scope="stack", title=title, generated=False, today=TODAY)
    assert e.fm["title"] == title


def test_two_cjk_titles_same_day_no_overwrite(tmp_repo):
    e1 = create_entry(tmp_repo, type="pitfall", domain="frontend",
                      scope="stack", title="中文标题甲", generated=False, today=TODAY)
    e2 = create_entry(tmp_repo, type="pitfall", domain="frontend",
                      scope="stack", title="中文标题乙", generated=False, today=TODAY)
    assert e1.path != e2.path
    assert e1.fm["title"] == "中文标题甲"
    assert e2.fm["title"] == "中文标题乙"
    assert e1.path.read_text(encoding="utf-8") != e2.path.read_text(encoding="utf-8")
    files = list((tmp_repo / "kb" / "pitfall" / "frontend").glob("*.md"))
    assert len(files) == 2
    # §48: 路径被 -2 去重掩盖时旧实现 id 仍静默相同 → _find 只命中一个,
    # 另一条 review/show/related 永久断链
    assert e1.fm["id"] != e2.fm["id"]


def test_id_collision_rejected_not_silent(tmp_repo, monkeypatch):
    """§48 实锤: id 是 4 hex 随机(空间 65536), 旧实现只给路径去重不给 id 校验,
    同日生日悖论 N=100 约 7.6% 撞车且写入瞬间零信号。修复后撞车必须抛错。"""
    from kb import new_entry
    monkeypatch.setattr(new_entry.secrets, "token_hex", lambda n: "abcd")
    create_entry(tmp_repo, type="howto", domain="process", scope="project",
                 title="甲", generated=True, today=TODAY)
    import pytest
    with pytest.raises(RuntimeError, match="unique id"):
        create_entry(tmp_repo, type="howto", domain="process", scope="project",
                     title="乙", generated=True, today=TODAY)


def test_id_collision_check_follows_id_not_filename(tmp_repo, monkeypatch):
    """占用集合按 id 内容筛, 不按文件名前缀: slug 可人工改名而 id 不可变,
    文件名代理会把改名过的同日条目漏出集合外(§42 同族: 代理指标≠事实源)。"""
    import pytest

    from kb import new_entry
    from kb.entry import parse_entry
    monkeypatch.setattr(new_entry.secrets, "token_hex", lambda n: "abcd")
    e1 = create_entry(tmp_repo, type="howto", domain="process", scope="project",
                      title="原名", generated=True, today=TODAY)   # id=…-abcd
    assert e1.fm["id"].endswith("-abcd")
    e1.path.rename(e1.path.parent / "renamed-by-hand.md")          # 人工改 slug
    renamed = e1.path.parent / "renamed-by-hand.md"
    # 文件名已无日期前缀, 按文件名筛会漏 → 同值 id 必须仍被判撞而抛错
    with pytest.raises(RuntimeError, match="unique id"):
        create_entry(tmp_repo, type="howto", domain="process", scope="project",
                     title="撞改名者", generated=True, today=TODAY)
    assert parse_entry(renamed).fm["id"] == e1.fm["id"]            # 改名条目 id 不变
