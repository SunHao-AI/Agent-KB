from pathlib import Path
from kb.lint import lint_repo
from kb.index import build_indexes
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


def test_generated_index_md_not_linted(tmp_repo):
    # 生成物 kb/INDEX.md 必须被 lint 跳过, 否则 kb index 之后 lint 恒误报
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified"))
    build_indexes(tmp_repo)
    assert (Path(tmp_repo) / "kb" / "INDEX.md").exists()
    assert lint_repo(tmp_repo, scope="project") == []


def test_h1_counting_ignores_fenced_code_blocks(tmp_repo):
    # 围栏代码块内的 "# " 开头行(shell/YAML 注释)不得计入 H1,
    # 否则迁移侧被迫把代码块里的 "# " 改成 "#" 规避, 损害内容保真
    entry = make_entry(scope="project", status="accepted", confidence="verified")
    entry += "\n```bash\n# 注释: 这是 shell 注释不是标题\n# 第二行注释\ndocker ps\n```\n"
    _put(tmp_repo, "kb/pitfall/frontend/a.md", entry)
    assert lint_repo(tmp_repo, scope="project") == []


def test_submodule_subtree_not_scanned(tmp_repo):
    # 项目 kb 根(docs/kb)内挂载的子模块仓 .agent-kb/kb/ 子树不属于本项目 lint 范围,
    # 全量 rglob 会把子仓生成物/条目误扫入, 造成误报与 scope 落位错乱
    _put(tmp_repo, "kb/.agent-kb/kb/INDEX.md",
         "# Knowledge Index\n\n- [demo](pitfall/frontend/x.md)\n")
    _put(tmp_repo, "kb/.agent-kb/kb/pitfall/frontend/x.md",
         make_entry(id="kb-20261012-ffff", scope="stack",
                    status="accepted", confidence="verified"))
    assert lint_repo(tmp_repo, scope="project") == []
