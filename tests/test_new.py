import datetime as dt
import re
from pathlib import Path
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
