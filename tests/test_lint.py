from pathlib import Path
from kb.lint import lint_repo
from conftest import make_entry


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_ok_for_valid_project_entry(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified"))
    assert lint_repo(tmp_repo, scope="project") == []


def test_flags_wrong_scope_in_agent_kb(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified"))
    errs = lint_repo(tmp_repo, scope="agent-kb")
    assert any("scope" in e for e in errs)


def test_flags_missing_required(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md", make_entry(domain=[]))
    errs = lint_repo(tmp_repo, scope="project")
    assert any("domain" in e for e in errs)


def test_flags_dangling_related(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", related=["kb-00000000-0000"]))
    errs = lint_repo(tmp_repo, scope="project")
    assert any("related" in e for e in errs)


def test_flags_duplicate_id(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified"))
    _put(tmp_repo, "kb/pitfall/frontend/b.md",
         make_entry(scope="project", status="accepted", confidence="verified"))
    errs = lint_repo(tmp_repo, scope="project")
    dups = [e for e in errs if "duplicate id" in e]
    assert len(dups) == 2


def test_no_frontmatter_reports_required_without_crash(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md", "# 纯正文\n\n没有任何 front-matter。\n")
    errs = lint_repo(tmp_repo, scope="project")
    assert errs
    assert any("required" in e for e in errs)


def test_supersedes_none_or_absent_not_flagged(tmp_repo):
    # supersedes 字段缺失: 不报引用错误
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified"))
    # supersedes 为 YAML 显式 null: 不报引用错误; superseded_by 指向存在的 id
    # (make_entry 用 f-string 渲染, None 会变成字面量 "None", 故手写 front-matter)
    _put(tmp_repo, "kb/pitfall/frontend/b.md",
         "---\nid: kb-20261012-b002\ntitle: demo2\ntype: pitfall\ndomain: [frontend]\n"
         "scope: project\nstatus: superseded\nconfidence: verified\n"
         "created: 2026-10-12\nupdated: 2026-10-12\n"
         "supersedes: null\nsuperseded_by: kb-20261012-7f3a\n---\n\n# demo2\n\n首段摘要。\n")
    assert lint_repo(tmp_repo, scope="project") == []
