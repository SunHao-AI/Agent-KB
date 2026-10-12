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
