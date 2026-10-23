from pathlib import Path
from kb import dedup
from kb import lint as lint_mod
from kb.lint import lint_repo
from kb.index import build_indexes
from conftest import make_entry


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_lint_threshold_is_dedup_constant():
    # 门槛常量单一事实源: lint 引用的 MIN_FP_LEN 必须是 dedup 模块同一对象,
    # 杜绝 lint 内再出现本地副本
    assert lint_mod.MIN_FP_LEN is dedup.MIN_FP_LEN


def test_lint_pitfall_requires_severity_error(tmp_repo):
    # taxonomy pitfall.requires=[severity] 已并入派生 schema: 缺 severity → error(阻断)
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261013-c3c3"), encoding="utf-8")
    errs = lint_repo(tmp_repo, scope="project")
    assert any("severity" in e and "required" in e and not e.startswith("warning: ")
               for e in errs)


def test_lint_reference_without_severity_ok(tmp_repo):
    # 条件必填只作用于声明 requires 的 type: reference 缺 severity 不受影响
    d = tmp_repo / "kb" / "reference" / "tooling"
    d.mkdir(parents=True)
    (d / "a.md").write_text(
        make_entry(id="kb-20261013-d4d4", type="reference", status="accepted",
                   confidence="verified"), encoding="utf-8")
    assert lint_repo(tmp_repo, scope="project") == []


def test_ok_for_valid_project_entry(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified",
                    severity="medium"))
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


def test_malformed_frontmatter_reports_required_without_crash(tmp_repo):
    # front-matter 根类型是 list(畸形)时不得崩溃, 按无 fm 处理报必填缺失
    _put(tmp_repo, "kb/pitfall/frontend/a.md", "---\n- just\n- a\n- list\n---\n\n# 标题\n\n正文。\n")
    errs = lint_repo(tmp_repo, scope="project")
    assert any("required" in e for e in errs)


def test_supersedes_none_or_absent_not_flagged(tmp_repo):
    # supersedes 字段缺失: 不报引用错误
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified",
                    severity="medium"))
    # supersedes 为 YAML 显式 null: 不报引用错误; superseded_by 指向存在的 id
    # (make_entry 用 f-string 渲染, None 会变成字面量 "None", 故手写 front-matter)
    _put(tmp_repo, "kb/pitfall/frontend/b.md",
         "---\nid: kb-20261012-b002\ntitle: demo2\ntype: pitfall\ndomain: [frontend]\n"
         "scope: project\nstatus: superseded\nseverity: low\nconfidence: verified\n"
         "created: 2026-10-12\nupdated: 2026-10-12\n"
         "supersedes: null\nsuperseded_by: kb-20261012-7f3a\n---\n\n# demo2\n\n首段摘要。\n")
    assert lint_repo(tmp_repo, scope="project") == []


def test_generated_index_md_not_linted(tmp_repo):
    # 生成物 kb/INDEX.md 必须被 lint 跳过, 否则 kb index 之后 lint 恒误报
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(scope="project", status="accepted", confidence="verified",
                    severity="medium"))
    build_indexes(tmp_repo)
    assert (Path(tmp_repo) / "kb" / "INDEX.md").exists()
    assert lint_repo(tmp_repo, scope="project") == []


def test_h1_counting_ignores_fenced_code_blocks(tmp_repo):
    # 围栏代码块内的 "# " 开头行(shell/YAML 注释)不得计入 H1,
    # 否则迁移侧被迫把代码块里的 "# " 改成 "#" 规避, 损害内容保真
    entry = make_entry(scope="project", status="accepted", confidence="verified",
                       severity="medium")
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


# --- Task 3: 指纹冲突检测(同仓 error / 跨仓 warning) + 占位根因 warning ---
# 注: 应触发用例的根因样本规范化后须 >= _MIN_FP_LEN(16), 否则被短源门槛跳过;
# brief 原样本("同一根因机制说明文字完全一致"=14、"跨仓相同根因的机制性描述"=12)
# 长度不足, 已在保持断言/消息格式/常量逐字不变的前提下加长样本至 >=16 字符。
def _pitfall(tmp_repo, eid, root_cause, title="t"):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    body = make_entry(id=eid, title=title)
    body = body + f"\n## 根因\n{root_cause}\n"
    (d / f"{eid}.md").write_text(body, encoding="utf-8")


def test_lint_same_repo_duplicate_fingerprint_is_error(tmp_repo):
    _pitfall(tmp_repo, "kb-20261013-aaaa", "同一根因机制说明文字完全一致的版本")
    _pitfall(tmp_repo, "kb-20261013-bbbb", "同一根因机制说明文字完全一致的版本")
    errs = lint_repo(tmp_repo)
    assert any("duplicate fingerprint" in e for e in errs)


def test_lint_short_source_not_compared(tmp_repo):
    _pitfall(tmp_repo, "kb-20261013-cccc", "太短")
    _pitfall(tmp_repo, "kb-20261013-dddd", "太短")
    assert not any("fingerprint" in e for e in lint_repo(tmp_repo))


def test_lint_cross_repo_warning(tmp_repo, tmp_path):
    other = tmp_path / "other"
    (other / "kb" / "pitfall" / "frontend").mkdir(parents=True)
    _pitfall(tmp_repo, "kb-20261013-eeee", "跨仓相同根因的机制性描述文字内容")
    body = (make_entry(id="kb-20261013-ffff", title="x")
            + "\n## 根因\n跨仓相同根因的机制性描述文字内容\n")
    (other / "kb" / "pitfall" / "frontend" / "x.md").write_text(body, encoding="utf-8")
    msgs = lint_repo(tmp_repo, cross_repos=[other])
    assert any(m.startswith("warning: ") and "same fingerprint" in m for m in msgs)
    assert not any(not m.startswith("warning: ") and "fingerprint" in m for m in msgs)


def test_lint_placeholder_root_cause_is_warning(tmp_repo):
    # 存在根因 H2 段但剥离 HTML 注释后为空 → 占位根因回流, 应出 warning(非 error)
    _pitfall(tmp_repo, "kb-20261013-a1a1", "<!-- TODO: 待人工补充机制性根因 -->")
    msgs = lint_repo(tmp_repo)
    assert any(m.startswith("warning: ") and "placeholder root-cause section" in m
               for m in msgs)


def test_lint_real_root_cause_no_placeholder_warning(tmp_repo):
    _pitfall(tmp_repo, "kb-20261013-b2b2", "这是真实根因机制说明文字且长度足够")
    msgs = lint_repo(tmp_repo)
    assert not any("placeholder root-cause section" in m for m in msgs)


# --- F4: 占位段检测泛化到该 type taxonomy sections 定义的每个 H2 段 ---
def _with_sections(tmp_repo, eid, sections):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    body = make_entry(id=eid)
    for header, content in sections:
        body += f"\n## {header}\n{content}\n"
    (d / f"{eid}.md").write_text(body, encoding="utf-8")


def test_lint_placeholder_verification_section_warning(tmp_repo):
    # 验证段存在但剥离 HTML 注释后为空 → placeholder 验证 warning(迁移侧占位回流防护)
    _with_sections(tmp_repo, "kb-20261013-e5e5", [
        ("根因", "真实机制说明文字内容且长度足够避免短源门槛"),
        ("验证", "<!-- TODO: 待补充验证 -->"),
    ])
    msgs = lint_repo(tmp_repo)
    assert any(m.startswith("warning: ") and "placeholder 验证 section" in m
               for m in msgs)
    assert not any("placeholder root-cause" in m for m in msgs)


def test_lint_placeholder_phenomenon_section_warning(tmp_repo):
    # 背景 / 现象 段(段名含空格与斜杠)同样纳入占位检测
    _with_sections(tmp_repo, "kb-20261013-f6f6", [
        ("背景 / 现象", "<!-- TODO -->"),
        ("根因", "真实机制说明文字内容且长度足够避免短源门槛"),
    ])
    msgs = lint_repo(tmp_repo)
    assert any("placeholder 背景 / 现象 section" in m for m in msgs)


def test_lint_filled_sections_no_placeholder_warning(tmp_repo):
    _with_sections(tmp_repo, "kb-20261013-a7a7", [
        ("背景 / 现象", "现象描述文字内容。"),
        ("根因", "真实机制说明文字内容且长度足够避免短源门槛"),
        ("验证", "验证步骤文字内容。"),
    ])
    msgs = lint_repo(tmp_repo)
    assert not any("placeholder" in m for m in msgs)


def test_lint_absent_section_not_flagged(tmp_repo):
    # 段缺失 ≠ 占位: 只有"存在该 H2 段且内容为空"才报, 缺段不报
    _pitfall(tmp_repo, "kb-20261013-b8b8", "真实机制说明文字内容且长度足够避免短源门槛")
    msgs = lint_repo(tmp_repo)
    assert not any("placeholder" in m for m in msgs)


# --- §42 第二十四轮: 条目发现规则唯一化, "进检索但免检"角落封死 ---
def test_stray_entry_at_kb_root_is_flagged_and_excluded(tmp_repo):
    """kb 根直下的带 id 散文件: lint 必须点名(失踪可发现), 且不再进 index
    (修复前 rglob 全量扫入: 坏 type/坏 status 照样进检索, 逃过 lint 全部校验)。"""
    from kb.index import _records
    _put(tmp_repo, "kb/loose.md",
         "---\nid: kb-20261013-c9c9\ntitle: 散文件\ntype: not-a-type\n"
         "domain: [backend]\nscope: project\nstatus: approved\nconfidence: verified\n"
         "created: 2026-10-13\nupdated: 2026-10-13\n---\n\n# 散文件\n\n正文。\n")
    errs = lint_repo(tmp_repo, scope="project")
    assert any("loose.md" in e and "散落的条目文件" in e for e in errs)
    live, draft = _records(tmp_repo, "r")
    assert [r["id"] for r in live + draft] == []   # 免检角落封死: 不进任何索引


def test_stray_entry_with_broken_yaml_is_flagged(tmp_repo):
    """§63: stray 判据此前只认"可解析 id"——front-matter 语法坏的散文件(作者显然
    想写条目, 同时滑了位置与语法)反而静默失踪: 不进 index、lint 两条通道点名不到
    (schema/语法错误路径只覆盖 iter_entry_paths 内的条目)。修复后语法坏的 kb 根
    散文件同样点名; 无 front-matter 的纯笔记不受误伤。"""
    _put(tmp_repo, "kb/broken-loose.md",
         "---\nid: kb-20261023-bbbb\ntags: [unclosed, flow\ntitle: 坏散文件\n"
         "type: pitfall\ndomain: [frontend]\nscope: project\nstatus: draft\n"
         "severity: low\nconfidence: speculative\ncreated: 2026-10-23\n"
         "updated: 2026-10-23\n---\n\n# 坏散文件\n\n正文。\n")
    _put(tmp_repo, "kb/plain-note.md", "# 随手笔记\n\n不是条目。\n")
    errs = lint_repo(tmp_repo, scope="project")
    assert any("broken-loose.md" in e and "散落的条目文件" in e for e in errs)
    assert not any("plain-note" in e for e in errs)


def test_all_readers_share_single_discovery_rule(tmp_repo):
    """lint/index/gate/query 对"哪些文件是条目"必须给出同一集合(§42 结构性保证:
    全部走 kb.entry.iter_entry_paths)。构造 契约内条目 + kb 根散文件 + 点目录
    外仓文件 三者, 各读源可见集合必须一致。"""
    from kb.entry import iter_entry_paths
    from kb.gate import _find
    from kb.index import _records
    from kb.query import due_review
    import datetime as dt
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261013-d1d1", scope="project", status="accepted",
                    confidence="verified", severity="medium"))
    _put(tmp_repo, "kb/loose.md",
         make_entry(id="kb-20261013-e2e2", scope="project"))
    _put(tmp_repo, "kb/.agent-kb/kb/pitfall/frontend/x.md",
         make_entry(id="kb-20261013-f3f3", scope="stack"))
    canon = {p.name for p in iter_entry_paths(tmp_repo)}
    assert canon == {"a.md"}
    assert {r["id"] for rs in _records(tmp_repo, "r") for r in rs} == {"kb-20261013-d1d1"}
    assert _find(tmp_repo, "kb-20261013-d1d1").name == "a.md"
    for bad_id in ("kb-20261013-e2e2", "kb-20261013-f3f3"):
        try:
            _find(tmp_repo, bad_id)
            raise AssertionError(f"{bad_id} 不应可发现")
        except FileNotFoundError:
            pass
    due = {d["id"] for d in due_review(tmp_repo, dt.date(2030, 1, 1))}
    assert due == {"kb-20261013-d1d1"}   # 散文件/外仓条目同样不入待复核
