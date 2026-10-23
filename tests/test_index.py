import json, re
from pathlib import Path
from kb.index import build_indexes, check_indexes
from conftest import make_entry, SAMPLE_FRONTMATTER


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_draft_excluded_from_main_index(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md", make_entry(status="accepted"))
    _put(tmp_repo, "kb/pitfall/frontend/d.md", make_entry(id="kb-20261012-abcd", status="draft"))
    md, jl, dj = build_indexes(tmp_repo)
    main = [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines()]
    draft = [json.loads(x) for x in dj.read_text(encoding="utf-8").splitlines()]
    assert {r["id"] for r in main} == {"kb-20261012-7f3a"}
    assert {r["id"] for r in draft} == {"kb-20261012-abcd"}
    assert md.exists()


def test_check_detects_stale(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md", make_entry(status="accepted"))
    build_indexes(tmp_repo)
    assert check_indexes(tmp_repo) is True
    _put(tmp_repo, "kb/pitfall/frontend/b.md", make_entry(id="kb-20261012-0001", status="accepted"))
    assert check_indexes(tmp_repo) is False


def test_index_md_links_relative_to_kb_dir(tmp_repo):
    # INDEX.md 位于 kb/ 内, 链接必须相对 kb/ 目录解析;
    # 若写成 repo 相对的 kb/... 会被解析成 kb/kb/... 而断裂
    _put(tmp_repo, "kb/pitfall/frontend/a.md", make_entry(status="accepted"))
    md, jl, dj = build_indexes(tmp_repo)
    content = md.read_text(encoding="utf-8")
    assert "](pitfall/frontend/a.md)" in content
    assert "](kb/" not in content
    # jsonl 的 path 字段保持 repo 相对不变
    rec = json.loads(jl.read_text(encoding="utf-8").splitlines()[0])
    assert rec["path"] == "kb/pitfall/frontend/a.md"


def test_index_md_multiline_title_keeps_one_line_per_record(tmp_repo):
    """§69 同族(第五十四轮): title 是 YAML 多行块时旧 _md 把一条记录劈成两行,
    INDEX.md"一记录一行"契约碎裂, 按行消费的 L2 面错位。修复后折叠为单行。"""
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(title='"第一行\\n第二行"', status="accepted"))
    _put(tmp_repo, "kb/pitfall/frontend/b.md",
         make_entry(id="kb-20261012-0002", title="正常", status="accepted"))
    md, _, _ = build_indexes(tmp_repo)
    items = [ln for ln in md.read_text(encoding="utf-8").splitlines()
             if ln.startswith("- [")]
    assert len(items) == 2                       # 两条记录恰好两行, 无游离行
    assert "第一行 第二行" in items[0]


def test_index_dedup_key_is_fingerprint(tmp_repo):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(SAMPLE_FRONTMATTER, encoding="utf-8")
    build_indexes(tmp_repo)
    rec = json.loads((tmp_repo / "kb" / "index.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert re.fullmatch(r"[0-9a-f]{12}", rec["dedup_key"])
