import datetime as dt
import pytest
from kb.gate import update_draft, review, set_scope, export_entry, GateViolation
from kb.entry import parse_entry
from conftest import make_entry

TODAY = dt.date(2026, 10, 14)


def _mk(tmp_repo, eid, status="draft", conf="speculative", scope="project", tags=None,
        title="demo"):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    body = make_entry(id=eid, status=status, confidence=conf, scope=scope,
                      title=title, tags=list(tags) if tags else [])
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


def test_accepted_sets_review_by_cycle(tmp_repo):
    """§38 实测: due_review/stat --due-review/AGENTS.md 工作流的消费链完好, 但生产方
    为零——review_by 从不被写入, accepted 条目永不到期, 待复核机制自上线起空转。
    修复: review(to=accepted) 落 review_by=accepted 日 + 周期(spec 示例为 1 年)。"""
    _mk(tmp_repo, "kb-20261014-rv01", status="proposed", conf="verified")
    e = review(tmp_repo, "kb-20261014-rv01", "accepted", today=TODAY)
    assert e.fm["review_by"] == "2027-10-14"
    # 未到期前不进待复核清单; 到期后出现
    from kb.query import due_review
    assert due_review(tmp_repo, dt.date(2027, 10, 13)) == []
    assert [r["id"] for r in due_review(tmp_repo, dt.date(2027, 10, 14))] == ["kb-20261014-rv01"]


def test_accepted_keeps_manual_future_review_by(tmp_repo):
    """人工显式设了更远的 review_by: accepted 不得覆盖(人工意图优先);
    设的是已过期值则刷新为新周期。两分支都从 proposed→accepted(合法流转)。"""
    p = _mk(tmp_repo, "kb-20261014-rv02", status="proposed", conf="verified")
    base = p.read_text(encoding="utf-8")
    p.write_text(base.replace("confidence: verified",
                              "confidence: verified\nreview_by: '2030-01-01'"),
                 encoding="utf-8")
    assert review(tmp_repo, "kb-20261014-rv02", "accepted",
                  today=TODAY).fm["review_by"] == "2030-01-01"
    # 重置回 proposed + 过期 review_by: accepted 时刷新为 今天+周期
    p.write_text(base.replace("confidence: verified",
                              "confidence: verified\nreview_by: '2026-01-01'"),
                 encoding="utf-8")
    assert review(tmp_repo, "kb-20261014-rv02", "accepted",
                  today=TODAY).fm["review_by"] == "2027-10-14"


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


def test_review_invalid_confidence_rejected(tmp_repo):
    """§56 同判据(第四十四轮 D-54): MCP kb_review 无 argparse choices, confidence
    拼错('verifed')旧实现**静默忽略**却照常 accepted + 写 verification 留痕——
    调用方以为提升 verified, 索引实际还是 probable(比报错危险的静默失真)。
    守门挂 review 头部, 枚举唯一事实源 taxonomy。"""
    _mk(tmp_repo, "kb-20261014-c1c1", status="proposed", conf="probable")
    with pytest.raises(GateViolation, match="unknown confidence"):
        review(tmp_repo, "kb-20261014-c1c1", "accepted", by="agent",
               confidence="verifed", evidence="x", today=TODAY)
    # 拒绝不留半成品: 状态仍 proposed、无 verification
    e = parse_entry(tmp_repo / "kb" / "pitfall" / "frontend" / "kb-20261014-c1c1.md")
    assert e.fm["status"] == "proposed" and "verification" not in e.fm
    # 合法值照常提升
    e = review(tmp_repo, "kb-20261014-c1c1", "accepted", by="agent",
               confidence="verified", evidence="实测", today=TODAY)
    assert e.fm["confidence"] == "verified"


# --- §43 第二十五轮: 写路径改 live 池字段后必须重建索引 ---
def test_review_accepted_makes_entry_searchable_immediately(tmp_repo):
    """红线1 闭环: agent 自审 accepted"无需等人工"——若 review 不重建 index.jsonl,
    刚 accepted 的条目对 kb_search 隐身(draft 本就不在 live 池), 面板/KPI/其他
    任务全部感知不到, 还会把同一条知识重复沉淀。"""
    import json
    from kb.search import search
    _mk(tmp_repo, "kb-20261014-b1b1", status="draft", conf="probable")
    assert search(tmp_repo, query="demo") == []      # draft 不可检索(设计内)
    review(tmp_repo, "kb-20261014-b1b1", "accepted", today=TODAY)
    ids = [json.loads(x)["id"] for x in
           (tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert "kb-20261014-b1b1" in ids                  # 索引即时入池
    assert search(tmp_repo, query="demo")[0]["id"] == "kb-20261014-b1b1"


def test_accepted_entry_visible_to_dedup_without_manual_index(tmp_repo):
    """探针同构: create→accepted 后不手动 kb index, 再沉淀近似条目必须被去重拦截
    (修复前 accepted 对 live 池与 draft 池双双隐身 → 重复沉淀成功)。"""
    from kb.gate import create_draft, DuplicateCandidate
    _mk(tmp_repo, "kb-20261014-b2b2", status="draft", conf="probable",
        title="Redis 连接池上限过低雪崩")
    review(tmp_repo, "kb-20261014-b2b2", "accepted", today=TODAY)
    with pytest.raises(DuplicateCandidate):
        create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="Redis 连接池上限过低雪崩", today=TODAY)


def test_set_scope_refreshes_index_scope_field(tmp_repo):
    """scope 是 live 池过滤字段: 不重建则索引滞留旧值, 双层检索按 scope 过滤错层。"""
    import json
    _mk(tmp_repo, "kb-20261014-b3b3", status="accepted", conf="verified")
    review_ok = parse_entry(tmp_repo / "kb" / "pitfall" / "frontend" / "kb-20261014-b3b3.md")
    assert review_ok.fm["scope"] == "project"
    set_scope(tmp_repo, "kb-20261014-b3b3", "stack", today=TODAY)
    rec = [json.loads(x) for x in
           (tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rec and rec[0]["scope"] == "stack"


# --- §44 第二十六轮: D-27 判据全仓普查补齐剩余写路径 ---
def test_create_draft_immediately_readable_by_get_entry(tmp_repo):
    """kb_create 返回 id 后立刻 kb_get: get_entry 的底座 query._records 只读两个
    索引文件, create_draft 不重建则刚建的 draft 读全文报 not found、stat 漏计。"""
    from kb.gate import create_draft
    from kb.query import get_entry, stat
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="刚沉淀的草稿", body="## 根因\n\n机制。\n", today=TODAY)
    text = get_entry(tmp_repo, e.fm["id"])
    assert text and "刚沉淀的草稿" in text
    assert stat(tmp_repo)["draft_backlog"] == 1


def test_update_draft_refreshes_draft_index(tmp_repo):
    """title/body 是 draft 索引列(summary 派生自 body): 不重建则 kb_get 面板/去重
    指纹全部滞留旧值。"""
    import json
    _mk(tmp_repo, "kb-20261014-c1c1", title="旧标题")
    update_draft(tmp_repo, "kb-20261014-c1c1", title="新标题", today=TODAY)
    rec = [json.loads(x) for x in
           (tmp_repo / "kb" / "index.draft.jsonl").read_text(encoding="utf-8").splitlines()
           if x.strip()]
    assert rec and rec[0]["title"] == "新标题"


def test_promote_refreshes_live_index_tags(tmp_repo):
    """tags 是 index.jsonl 列(kb_search tag 过滤/面板展示): promote 打建议标签后
    不重建则消费面仍见旧标签。"""
    import json
    from kb.promote import promote
    _mk(tmp_repo, "kb-20261014-c2c2", status="accepted", conf="verified")
    promote(tmp_repo, "kb-20261014-c2c2", "stack", today=TODAY)
    rec = [json.loads(x) for x in
           (tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8").splitlines()
           if x.strip()]
    assert rec and "needs-scope-review" in rec[0]["tags"]


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


def test_export_survives_non_dict_source(tmp_repo, tmp_path):
    """§66(第五十三轮): source 回填相邻两行防线都不等厚——`or {}` 防 None 漏
    标量({**'manual'} TypeError), `.get('source', {})` 默认值对"键存在为 null"
    不生效(None.get AttributeError)。front-matter 是不可信输入, 两种手工形态
    都写得出来, 修复后按缺失处理+warn, 搬移照常。"""
    kb2 = tmp_path / "agentkb4"
    (kb2 / "kb").mkdir(parents=True)
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    for i, src_line in (("1a1a", "source:"), ("1b1b", "source: manual")):
        (d / f"kb-20261014-{i}.md").write_text(
            make_entry(id=f"kb-20261014-{i}").replace(
                "confidence: speculative",
                f"confidence: speculative\n{src_line}"), encoding="utf-8")
        dst = export_entry(tmp_repo, kb2, f"kb-20261014-{i}",
                           to_scope="stack", today=TODAY)
        fm = parse_entry(dst).fm
        assert isinstance(fm["source"]["project"], str) and fm["source"]["project"]


def test_export_conflict_rejected(tmp_repo, tmp_path):
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb" / "pitfall" / "frontend").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0b0b")
    (kb2 / "kb" / "pitfall" / "frontend" / "kb-20261014-0b0b.md").write_text(
        make_entry(id="kb-20261014-0b0b", scope="stack"), encoding="utf-8")
    with pytest.raises(GateViolation, match="exists"):
        export_entry(tmp_repo, kb2, "kb-20261014-0b0b", to_scope="stack")


def test_export_rejects_same_id_different_slug(tmp_repo, tmp_path):
    """§54 实锤: 路径冲突检查挡不住"同 id 不同 slug"(目标仓有早前从别处上提的
    同 id 条目)。搬入=破坏性(删源)后目标仓同 id 双条目、_find 断链, 事后 lint
    才知=两仓回不去。主键碰撞必须按 id 查, 路径只是派生投影。"""
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb" / "pitfall" / "frontend").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0f0f")            # 源 slug: 默认(标题派生)
    (kb2 / "kb" / "pitfall" / "frontend" / "earlier-import.md").write_text(
        make_entry(id="kb-20261014-0f0f", title="早前上提", scope="stack"),
        encoding="utf-8")
    src = tmp_repo / "kb" / "pitfall" / "frontend"
    with pytest.raises(GateViolation, match="already has id"):
        export_entry(tmp_repo, kb2, "kb-20261014-0f0f", to_scope="stack")
    assert any(p.read_text(encoding="utf-8").count("id: kb-20261014-0f0f")
               for p in src.glob("*.md"))         # 拒收不得删源


def test_export_rejects_project_scope_target(tmp_repo, tmp_path):
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-0c0c")
    with pytest.raises(ValueError):
        export_entry(tmp_repo, kb2, "kb-20261014-0c0c", to_scope="project")


def test_export_rejects_target_repo_without_kb_dir(tmp_repo, tmp_path):
    """§32 实测: --to-repo 路径打错时旧实现 mkdir(parents=True) 静默建假仓并
    搬移+删源, 条目从两仓索引双双消失。必须前置校验拒绝且不删源。"""
    fake = tmp_path / "agent-kb-typo"   # 故意不建 kb/
    _mk(tmp_repo, "kb-20261014-1a1a")
    src = tmp_repo / "kb" / "pitfall" / "frontend" / "kb-20261014-1a1a.md"
    with pytest.raises(GateViolation, match="kb/"):
        export_entry(tmp_repo, fake, "kb-20261014-1a1a", to_scope="stack")
    assert src.exists()                 # 失败不得删源
    assert not fake.exists()            # 不得建假仓


def test_export_rebuilds_both_indexes(tmp_repo, tmp_path):
    """§32 实测: 旧实现搬移后两仓 index 均滞留——源仓检索命中已删条目,
    目标仓检索不到新条目。搬移必须重建双方索引。"""
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-2b2b", status="accepted", conf="verified")
    export_entry(tmp_repo, kb2, "kb-20261014-2b2b", to_scope="stack", today=TODAY)
    src_jl = (tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8")
    dst_jl = (kb2 / "kb" / "index.jsonl").read_text(encoding="utf-8")
    assert "kb-20261014-2b2b" not in src_jl   # 源仓索引已除名
    assert "kb-20261014-2b2b" in dst_jl       # 目标仓索引已入账


def test_export_warns_on_unreviewed_entry(tmp_repo, tmp_path, capsys):
    kb2 = tmp_path / "agentkb"
    (kb2 / "kb").mkdir(parents=True)
    _mk(tmp_repo, "kb-20261014-3c3c")          # make_entry 默认 draft/speculative
    export_entry(tmp_repo, kb2, "kb-20261014-3c3c", to_scope="stack", today=TODAY)
    assert "未终审" in capsys.readouterr().err  # 搬移成功但必须警示
