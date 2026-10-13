import json
import datetime as dt
from kb.cli import main
from conftest import make_entry


def _put(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_cli_index_then_search_json(tmp_repo, capsys):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", title="Vite", status="accepted"))
    assert main(["index", "--repo", str(tmp_repo)]) == 0
    code = main(["search", "--repo", str(tmp_repo), "--query", "vite"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "kb-20261012-aaaa" in printed


def test_cli_lint_nonzero_on_error(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md", make_entry(domain=[]))
    assert main(["lint", "--repo", str(tmp_repo)]) != 0


def test_cli_new_writes_file(tmp_repo):
    code = main(["new", "pitfall", "--repo", str(tmp_repo), "--domain", "frontend",
                 "--scope", "project", "--title", "Demo", "--generated"])
    assert code == 0
    assert list((tmp_repo / "kb" / "pitfall" / "frontend").glob("*.md"))


def test_cli_index_records_repo_name(tmp_repo):
    # 默认 repo 名取 --repo 目录名; 显式 --repo-name 优先
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", status="accepted"))
    assert main(["index", "--repo", str(tmp_repo)]) == 0
    rec = json.loads((tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8"))
    assert rec["repo"] == tmp_repo.name
    assert main(["index", "--repo", str(tmp_repo), "--repo-name", "my-kb"]) == 0
    rec = json.loads((tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8"))
    assert rec["repo"] == "my-kb"


def test_cli_lint_rejects_invalid_scope(tmp_repo):
    # argparse choices 拒绝非法 scope, 拼错立即 exit 2 而非静默关闭落位检查
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["lint", "--repo", str(tmp_repo), "--scope", "projekt"])
    assert exc.value.code == 2


def test_cli_review_rejects_illegal_transition(tmp_repo, capsys):
    d = tmp_repo / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-c1c1", status="accepted",
                                       confidence="verified"), encoding="utf-8")
    assert main(["review", "kb-20261014-c1c1", "--to", "draft", "--repo", str(tmp_repo)]) == 1
    assert "kb error:" in capsys.readouterr().err


def test_cli_review_success_prints_json(tmp_repo, capsys):
    # 成功路径必须可 JSON 序列化输出(Entry 不可直接 dumps, Task 11 实测曾崩溃)
    d = tmp_repo / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-c2c2", status="draft",
                                       confidence="probable"), encoding="utf-8")
    assert main(["review", "kb-20261014-c2c2", "--to", "proposed",
                 "--repo", str(tmp_repo)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "kb-20261014-c2c2" and out["status"] == "proposed"


def test_cli_new_generated_scope_ignored(tmp_repo, capsys):
    rc = main(["new", "pitfall", "--domain", "frontend", "--title", "门控新建",
               "--scope", "stack", "--generated", "--repo", str(tmp_repo)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "note: generated entries are always scope=project" in err
    md = next((tmp_repo / "kb" / "pitfall" / "frontend").glob("*.md"))
    assert "scope: project" in md.read_text(encoding="utf-8")


def test_cli_stat_needs_scope_md(tmp_repo, capsys):
    d = tmp_repo / "kb" / "pitfall" / "backend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-d2d2", title="待认定",
                                       tags=["needs-scope-review"]), encoding="utf-8")
    assert main(["stat", "--needs-scope", "--format", "md", "--repo", str(tmp_repo)]) == 0
    assert "待认定" in capsys.readouterr().out


def test_cli_search_agent_kb_layers(tmp_path, capsys):
    # 双层检索: 项目层 + agent-kb 层各命中一条, repo 字段区分来源
    proj_kb = tmp_path / "proj"
    (proj_kb / "kb").mkdir(parents=True)
    _put(proj_kb, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261014-e1e1", title="projvite", status="accepted"))
    stack_kb = tmp_path / "stackkb"
    (stack_kb / "kb").mkdir(parents=True)
    _put(stack_kb, "kb/pitfall/backend/b.md",
         make_entry(id="kb-20261014-f2f2", title="stackvite", status="accepted",
                    scope="stack"))
    from kb.index import build_indexes
    build_indexes(proj_kb, repo_name=proj_kb.name)
    build_indexes(stack_kb, repo_name=stack_kb.name)
    assert main(["search", "--repo", str(proj_kb), "--agent-kb", str(stack_kb),
                 "--query", "vite"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["repo"] for r in rows} == {proj_kb.name, stack_kb.name}
