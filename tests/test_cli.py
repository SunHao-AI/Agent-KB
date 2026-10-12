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
