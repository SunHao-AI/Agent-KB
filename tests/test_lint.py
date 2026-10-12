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
