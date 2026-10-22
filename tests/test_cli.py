import json
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


def test_cli_missing_repo_path_errors(tmp_path, capsys):
    """§33 实测: --repo 指向不存在路径时搜索面曾静默返回 [] + exit 0, 对 Agent
    消费方等于把"路径打错"报成"库里没这条知识"。必须非零退出且 stderr 可辨。"""
    missing = tmp_path / "no-such-repo"
    assert main(["search", "--query", "vite", "--repo", str(missing)]) == 1
    assert "路径不存在" in capsys.readouterr().err
    # 存在但无匹配的目录不得被误伤(校验只拦"不存在", 不拦"空库")
    assert main(["search", "--query", "vite", "--repo", str(tmp_path)]) == 0


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
    assert rec["repo"] == tmp_repo.name.lower()
    assert main(["index", "--repo", str(tmp_repo), "--repo-name", "my-kb"]) == 0
    rec = json.loads((tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8"))
    assert rec["repo"] == "my-kb"


def test_index_repo_name_case_normalized(tmp_path):
    # 目录显示名大小写不得影响 repo 字段: 本地克隆为 `Agent-KB` 而 index 以规范名
    # `agent-kb` 提交时, 旧实现按目录名重算致 `index --check` 恒 stale (fixwave-A 偏差 1)
    repo = tmp_path / "Agent-KB"
    _put(repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261014-a1a1", status="accepted"))
    assert main(["index", "--repo", str(repo)]) == 0
    rec = json.loads((repo / "kb" / "index.jsonl").read_text(encoding="utf-8"))
    assert rec["repo"] == "agent-kb"
    assert main(["index", "--check", "--repo", str(repo)]) == 0


def test_cli_lint_rejects_invalid_scope(tmp_repo):
    # argparse choices 拒绝非法 scope, 拼错立即 exit 2 而非静默关闭落位检查
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["lint", "--repo", str(tmp_repo), "--scope", "projekt"])
    assert exc.value.code == 2


def _placeholder_entry(eid, root="真实机制说明文字内容且长度足够避免短源门槛"):
    return (make_entry(id=eid, status="accepted", scope="stack",
                       confidence="verified", severity="low")
            + f"\n## 根因\n{root}\n"
            + "\n## 验证\n<!-- TODO -->\n")


# stack scope 条目必须配 --scope agent-kb lint, 否则触发 scope 硬错误而非本测试考察的 warning 路径
_LINT = ["lint", "--scope", "agent-kb"]


def test_cli_lint_strict_baseline_blocks_new_warning_only(tmp_repo):
    # 存量 warning 入 baseline 后 strict 放行; 新增占位条目(不在 baseline)即拦截
    _put(tmp_repo, "kb/pitfall/backend/a.md", _placeholder_entry("kb-20261014-b1b1", "机制甲说明文字内容且长度足够避免短源门槛"))
    assert main(_LINT + ["--repo", str(tmp_repo), "--update-baseline"]) == 0
    assert main(_LINT + ["--repo", str(tmp_repo), "--strict"]) == 0
    _put(tmp_repo, "kb/pitfall/backend/b.md", _placeholder_entry("kb-20261014-b2b2", "机制乙说明文字内容且长度足够避免短源门槛"))
    assert main(_LINT + ["--repo", str(tmp_repo), "--strict"]) == 1
    # 非 strict 保持既有语义: warning 不阻断
    assert main(_LINT + ["--repo", str(tmp_repo)]) == 0


def test_cli_lint_update_baseline_shrinks_fixed(tmp_repo):
    _put(tmp_repo, "kb/pitfall/backend/a.md", _placeholder_entry("kb-20261014-c1c1"))
    assert main(_LINT + ["--repo", str(tmp_repo), "--update-baseline"]) == 0
    # 回填后 baseline 剩 1 条过期豁免: lint 提示收缩但不阻断; 收缩后 strict 仍绿
    (tmp_repo / "kb" / "pitfall" / "backend" / "a.md").write_text(
        make_entry(id="kb-20261014-c1c1", status="accepted", scope="stack",
                   confidence="verified", severity="low")
        + "\n## 根因\n真实机制说明文字内容且长度足够避免短源门槛\n"
        + "\n## 验证\n实测步骤文字内容。\n", encoding="utf-8")
    assert main(_LINT + ["--repo", str(tmp_repo), "--strict"]) == 0
    assert main(_LINT + ["--repo", str(tmp_repo), "--update-baseline"]) == 0
    assert (tmp_repo / ".kb-lint-baseline").read_text(encoding="utf-8") == ""


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


def test_cli_review_accepted_with_evidence_writes_verification(tmp_repo, capsys):
    # --evidence 仅在 --to accepted 时写入 verification 留痕(人工终审, 非自审标记)
    d = tmp_repo / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-c4c4", status="proposed",
                                       confidence="verified"), encoding="utf-8")
    assert main(["review", "kb-20261014-c4c4", "--to", "accepted",
                 "--evidence", "loadtest 21.4->51.5 QPS", "--repo", str(tmp_repo)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "accepted"
    assert out["verification"]["evidence"] == "loadtest 21.4->51.5 QPS"
    assert "auto-reviewed" not in (out.get("tags") or [])


def test_cli_review_as_agent_accept_writes_audit_trail(tmp_repo, capsys):
    # B1: --as-agent 对齐 MCP kb_review 自审留痕(verified_by + auto-reviewed)
    d = tmp_repo / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-c5c5", status="draft",
                                       confidence="speculative"), encoding="utf-8")
    assert main(["review", "kb-20261014-c5c5", "--to", "accepted", "--as-agent",
                 "--confidence", "verified", "--evidence", "ab-bench 0 丢行",
                 "--repo", str(tmp_repo)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "accepted" and out["confidence"] == "verified"
    assert out["verified_by"] == "agent" and "auto-reviewed" in out["tags"]
    assert out["verification"]["evidence"] == "ab-bench 0 丢行"


def test_cli_review_as_agent_accept_requires_evidence(tmp_repo, capsys):
    # B1: 自审 accepted 缺 evidence 在 CLI 面即拒(与 MCP GateViolation 对齐)
    d = tmp_repo / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-c6c6", status="draft",
                                       confidence="verified"), encoding="utf-8")
    assert main(["review", "kb-20261014-c6c6", "--to", "accepted", "--as-agent",
                 "--repo", str(tmp_repo)]) == 1
    assert "--evidence" in capsys.readouterr().err


def test_cli_set_scope_success_prints_json(tmp_repo, capsys):
    # 成功路径必须可 JSON 序列化输出(与 review 同款缺陷, Entry 不可直接 dumps)
    d = tmp_repo / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-c3c3", status="draft",
                                       confidence="probable",
                                       tags=["needs-scope-review"]), encoding="utf-8")
    assert main(["set-scope", "kb-20261014-c3c3", "project",
                 "--repo", str(tmp_repo)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "kb-20261014-c3c3" and out["scope"] == "project"
    assert "needs-scope-review" not in (out.get("tags") or [])


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
