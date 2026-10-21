import datetime as dt
import pytest
from kb.gate import update_draft, review, set_scope, export_entry, GateViolation
from kb.entry import parse_entry
from conftest import make_entry

TODAY = dt.date(2026, 10, 14)


def _mk(tmp_repo, eid, status="draft", conf="speculative", scope="project", tags=None):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    body = make_entry(id=eid, status=status, confidence=conf, scope=scope,
                      tags=list(tags) if tags else [])
    p = d / f"{eid}.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_update_draft_ok(tmp_repo):
    _mk(tmp_repo, "kb-20261014-aaaa")
    e = update_draft(tmp_repo, "kb-20261014-aaaa", body="## 根因\n新机制。\n", today=TODAY)
    assert e.body.count("新机制") == 1 and e.fm["updated"] == "2026-10-14"
    assert e.fm["status"] == "draft"


def test_update_draft_rejects_accepted(tmp_repo):
    _mk(tmp_repo, "kb-20261014-bbbb", status="accepted", conf="verified")
    with pytest.raises(GateViolation, match="accepted"):
        update_draft(tmp_repo, "kb-20261014-bbbb", body="x")


def test_update_draft_missing_id(tmp_repo):
    with pytest.raises(FileNotFoundError):
        update_draft(tmp_repo, "kb-20261014-9999", body="x")


@pytest.mark.parametrize("frm,conf,to,ok", [
    ("draft", "probable", "proposed", True),
    ("draft", "probable", "accepted", True),
    ("draft", "speculative", "accepted", False),
    ("draft", "probable", "deprecated", True),
    ("proposed", "probable", "draft", True),
    ("proposed", "probable", "accepted", True),
    ("proposed", "speculative", "accepted", False),
    ("accepted", "verified", "deprecated", True),
    ("accepted", "verified", "superseded", True),
    ("accepted", "verified", "draft", False),
    ("deprecated", "verified", "accepted", False),
])
def test_review_transitions(tmp_repo, frm, conf, to, ok):
    _mk(tmp_repo, "kb-20261014-cccc", status=frm, conf=conf)
    if ok:
        assert review(tmp_repo, "kb-20261014-cccc", to).fm["status"] == to
    else:
        with pytest.raises(GateViolation):
            review(tmp_repo, "kb-20261014-cccc", to)


def test_review_accept_requires_non_speculative(tmp_repo):
    _mk(tmp_repo, "kb-20261014-dddd", status="proposed", conf="speculative")
    with pytest.raises(GateViolation, match="speculative"):
        review(tmp_repo, "kb-20261014-dddd", "accepted")


def test_review_agent_accept_adds_audit_trail(tmp_repo):
    _mk(tmp_repo, "kb-20261014-a1a1", status="draft", conf="verified")
    e = review(tmp_repo, "kb-20261014-a1a1", "accepted", by="agent", today=TODAY)
    assert e.fm["status"] == "accepted"
    assert "auto-reviewed" in e.fm.get("tags", [])
    assert e.fm.get("verified_by") == "agent"


def test_review_human_accept_has_no_audit_trail(tmp_repo):
    _mk(tmp_repo, "kb-20261014-a2a2", status="draft", conf="verified")
    e = review(tmp_repo, "kb-20261014-a2a2", "accepted", today=TODAY)
    assert "auto-reviewed" not in (e.fm.get("tags") or [])
    assert "verified_by" not in e.fm
    assert "verification" not in e.fm


def test_review_human_accept_with_evidence_writes_verification(tmp_repo):
    # 人工终审带 --evidence: 写 verification 留痕, 但不打 auto-reviewed/verified_by
    _mk(tmp_repo, "kb-20261014-a4a4", status="proposed", conf="probable")
    e = review(tmp_repo, "kb-20261014-a4a4", "accepted", today=TODAY,
               confidence="verified", evidence="perf 报告 §7.2: 21.4→51.5 QPS")
    assert e.fm["status"] == "accepted"
    assert e.fm["confidence"] == "verified"
    assert e.fm["verification"] == {"evidence": "perf 报告 §7.2: 21.4→51.5 QPS",
                                    "reviewed_at": "2026-10-14"}
    assert "auto-reviewed" not in (e.fm.get("tags") or [])
    assert "verified_by" not in e.fm


def test_review_agent_accept_still_blocks_speculative(tmp_repo):
    _mk(tmp_repo, "kb-20261014-a3a3", status="draft", conf="speculative")
    with pytest.raises(GateViolation, match="speculative"):
        review(tmp_repo, "kb-20261014-a3a3", "accepted", by="agent")


def test_set_scope_strips_needs_scope_review(tmp_repo):
    _mk(tmp_repo, "kb-20261014-eeee", tags=["needs-scope-review", "vite"])
    e = set_scope(tmp_repo, "kb-20261014-eeee", "project", today=TODAY)
    assert e.fm["scope"] == "project" and e.fm["tags"] == ["vite"]


def test_set_scope_rejects_bad_enum(tmp_repo):
    _mk(tmp_repo, "kb-20261014-ffff")
    with pytest.raises(ValueError):
        set_scope(tmp_repo, "kb-20261014-ffff", "global")


def test_export_moves_entry(tmp_repo, tmp_path):
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0a0a", tags=["needs-scope-review"])
    dst = export_entry(tmp_repo, kb2, "kb-20261014-0a0a", to_scope="stack", today=TODAY)
    assert dst.exists() and not (tmp_repo / "kb" / "pitfall" / "frontend" / "kb-20261014-0a0a.md").exists()
    e = parse_entry(dst)
    assert e.fm["scope"] == "stack" and "needs-scope-review" not in e.fm.get("tags", [])


def test_export_project_name_prefers_git_root(tmp_repo, tmp_path):
    # B2: --repo 指仓内子目录(docs/kb 结构)时, source.project 取 .git 祖先名
    # 而非目录尾段(旧行为会把 'docs' 写进 source.project)
    fake = tmp_path / "my-business-repo"
    (fake / ".git").mkdir(parents=True)
    kb_dir = fake / "docs"
    (kb_dir / "kb" / "pitfall" / "frontend").mkdir(parents=True)
    (kb_dir / "kb" / "pitfall" / "frontend" / "kb-20261014-0d0d.md").write_text(
        make_entry(id="kb-20261014-0d0d"), encoding="utf-8")
    kb2 = tmp_path / "agentkb2"
    (kb2 / "kb").mkdir(parents=True)
    dst = export_entry(kb_dir, kb2, "kb-20261014-0d0d", to_scope="stack", today=TODAY)
    assert parse_entry(dst).fm["source"]["project"] == "my-business-repo"


def test_export_keeps_existing_source_project(tmp_repo, tmp_path):
    # 已有 source.project 不被覆盖
    kb2 = tmp_path / "agentkb3"
    (kb2 / "kb").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0e0e")
    p = tmp_repo / "kb" / "pitfall" / "frontend" / "kb-20261014-0e0e.md"
    p.write_text(make_entry(id="kb-20261014-0e0e",
                            source={"project": "orig-name"}), encoding="utf-8")
    dst = export_entry(tmp_repo, kb2, "kb-20261014-0e0e", to_scope="stack", today=TODAY)
    assert parse_entry(dst).fm["source"]["project"] == "orig-name"


def test_export_conflict_rejected(tmp_repo, tmp_path):
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb" / "pitfall" / "frontend").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0b0b")
    (kb2 / "kb" / "pitfall" / "frontend" / "kb-20261014-0b0b.md").write_text(
        make_entry(id="kb-20261014-0b0b", scope="stack"), encoding="utf-8")
    with pytest.raises(GateViolation, match="exists"):
        export_entry(tmp_repo, kb2, "kb-20261014-0b0b", to_scope="stack")


def test_export_rejects_project_scope_target(tmp_repo, tmp_path):
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0c0c")
    with pytest.raises(ValueError):
        export_entry(tmp_repo, kb2, "kb-20261014-0c0c", to_scope="project")
