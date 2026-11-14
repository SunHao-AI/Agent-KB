import json, re
from pathlib import Path
from kb.index import build_indexes, check_indexes, resolve_repo_name
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


def test_check_ignores_draft_index_drift(tmp_repo):
    """draft 索引是他人 WIP 的生成物, 不进 --check 门禁(2026-10-29 实际踩到):
    业务仓工作区常有未提交的 QA draft, 提交时还原 index.draft.jsonl 就会永久红,
    直到那批 draft 收口——门禁拦的是"live 面漂移", 不是 WIP 未入库。
    live 面(INDEX.md / index.jsonl)漂移仍必须检出。"""
    _put(tmp_repo, "kb/pitfall/frontend/a.md", make_entry(status="accepted"))
    _put(tmp_repo, "kb/pitfall/frontend/d.md", make_entry(id="kb-20261012-abcd", status="draft"))
    build_indexes(tmp_repo)
    assert check_indexes(tmp_repo) is True
    (tmp_repo / "kb" / "index.draft.jsonl").write_text("", encoding="utf-8")  # 模拟 git restore
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


def test_resolve_repo_name_reads_persisted_label(tmp_repo):
    """载体目录名与固化 repo 标签不同源时, 校验侧必须从 index.jsonl 自取。

    业务仓项目层挂在 docs/ 下、通用层挂在 .agent-kb/ 下, 而生成时写入的是仓名 /
    agent-kb。旧实现(cli.py 与 bootstrap.py doctor)从目录名反推再与固化值全等
    比对 → `index --check` 与 doctor 的 index fresh 恒判 stale, 按建议重建也消不掉。
    """
    _put(tmp_repo, "kb/pitfall/backend/a.md", make_entry(status="accepted"))
    build_indexes(tmp_repo, repo_name="flysee-video-setting")
    assert resolve_repo_name(tmp_repo) == "flysee-video-setting"
    assert check_indexes(tmp_repo, repo_name="flysee-video-setting") is True
    # 反证: 按载体目录名反推(旧口径)必然假阳性
    assert check_indexes(tmp_repo, repo_name=tmp_repo.name.lower()) is False
    # 显式 --repo-name 优先于自取
    assert resolve_repo_name(tmp_repo, "my-kb") == "my-kb"


def test_resolve_repo_name_falls_back_only_without_index(tmp_repo):
    """索引不存在(首次构建)才回落目录名小写; 有索引但读不到 repo 字段同样回落。"""
    assert resolve_repo_name(tmp_repo / "docs") == "docs"
    (tmp_repo / "kb" / "index.jsonl").unlink(missing_ok=True)
    assert resolve_repo_name(tmp_repo) == tmp_repo.name.lower()
    (tmp_repo / "kb" / "index.jsonl").write_text("", encoding="utf-8")
    assert resolve_repo_name(tmp_repo) == tmp_repo.name.lower()


def _strip_field(index_path, key):
    """从已提交 index.jsonl 逐行删掉某键(模拟 v1 索引: 尚未带该字段)。"""
    rows = [json.loads(ln) for ln in
            index_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for r in rows:
        r.pop(key, None)
    index_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


def test_check_tolerates_v1_rows_missing_origin_uri(tmp_repo):
    """跨仓索引形状版本兼容(spec 2026-11-14 §1): 业务仓钉住的旧 kb 码不注入
    origin/uri, 但门禁回落到 Agent-KB 主仓新码重算 → 若逐字节比对则 web/algorithm
    下次触碰 kb 的推送必被 index --check 拦下(2026-11-14 独立实测: web 121 行
    rc=1)。缺 origin/uri 的 v1 行须视为契约默认值(local/null)而放行, 且无需业务仓
    重建索引(否则等于强制其用自己钉不住的新形状整体重写)。"""
    _put(tmp_repo, "kb/pitfall/backend/a.md", make_entry(status="accepted"))
    build_indexes(tmp_repo, repo_name="flysee_video_web")
    jl = tmp_repo / "kb" / "index.jsonl"
    assert check_indexes(tmp_repo, repo_name="flysee_video_web") is True
    # 删成 v1 形状(无 origin/uri): 仍判新鲜
    _strip_field(jl, "origin")
    _strip_field(jl, "uri")
    assert check_indexes(tmp_repo, repo_name="flysee_video_web") is True


def test_check_still_strict_beyond_origin_uri(tmp_repo):
    """向后兼容只豁免缺 origin/uri: 其余字段漂移、行数不符、origin 值错都仍判 stale,
    否则等于把整条 --check 门禁掏空。"""
    _put(tmp_repo, "kb/pitfall/backend/a.md", make_entry(status="accepted"))
    build_indexes(tmp_repo, repo_name="r")
    jl = tmp_repo / "kb" / "index.jsonl"
    # (1) 删 origin/uri → 仍 True(基准, 见上一用例)
    _strip_field(jl, "origin")
    _strip_field(jl, "uri")
    assert check_indexes(tmp_repo, repo_name="r") is True
    # (2) 在 v1 形状上再加一处真漂移(改 summary) → False
    rows = [json.loads(ln) for ln in jl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows[0]["summary"] = "被篡改的摘要"
    jl.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
                  encoding="utf-8")
    assert check_indexes(tmp_repo, repo_name="r") is False
    # (3) origin 值错(非 local) → False
    build_indexes(tmp_repo, repo_name="r")
    _strip_field(jl, "origin")
    _strip_field(jl, "uri")
    rows = [json.loads(ln) for ln in jl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows[0]["origin"] = "ext:feishu"
    jl.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
                  encoding="utf-8")
    assert check_indexes(tmp_repo, repo_name="r") is False
    # (4) 行数不符(v1 少一行条目) → False
    build_indexes(tmp_repo, repo_name="r")
    _put(tmp_repo, "kb/pitfall/backend/b.md",
         make_entry(id="kb-20261012-0002", status="accepted"))
    assert check_indexes(tmp_repo, repo_name="r") is False


def test_check_malformed_jsonl_is_stale_not_crash(tmp_repo):
    """committed index.jsonl 语法坏(手改/半写) → 判 stale 返 False, 不抛异常。"""
    _put(tmp_repo, "kb/pitfall/backend/a.md", make_entry(status="accepted"))
    build_indexes(tmp_repo, repo_name="r")
    (tmp_repo / "kb" / "index.jsonl").write_text("{ not json\n", encoding="utf-8")
    assert check_indexes(tmp_repo, repo_name="r") is False


def test_records_carry_federation_fields(tmp_repo):
    """联邦 L2 记录契约(spec 2026-11-14 §1): 本地记录恒 origin=local, uri=null。"""
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261114-aaaa", status="accepted"),
                            encoding="utf-8")
    (d / "w.md").write_text(make_entry(id="kb-20261114-bbbb", status="draft"),
                            encoding="utf-8")
    build_indexes(tmp_repo, repo_name="demo")
    for name in ("index.jsonl", "index.draft.jsonl"):
        rows = [json.loads(ln) for ln in
                (tmp_repo / "kb" / name).read_text(encoding="utf-8").splitlines()]
        assert rows and all(r["origin"] == "local" and r["uri"] is None for r in rows)
    # 检索面透传零破坏: search 行含新字段仍命中(联邦适配器只需产出同形状行)
    # (brief 原文 query="Vite" 在本 fixture 下零命中——make_entry 默认 title=demo,
    # 正文无 Vite; 查询词改为命中 fixture 实际内容, 断言意图不变)
    from kb.search import search
    hits = search(tmp_repo, query="demo", limit=5)
    assert hits and hits[0]["origin"] == "local"
