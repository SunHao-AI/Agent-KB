import pathlib
from kb.entry import parse_entry, dump_entry


def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "kb" / "pitfall" / "frontend" / "x.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_extracts_frontmatter_and_body(tmp_repo):
    from conftest import SAMPLE_FRONTMATTER
    p = _write(tmp_repo, SAMPLE_FRONTMATTER)
    e = parse_entry(p)
    assert e.fm["id"] == "kb-20261012-7f3a"
    assert e.fm["domain"] == ["frontend", "build"]
    assert e.h1() == "Vite HMR 在 Windows 下不生效"
    assert e.summary().startswith("第一段")


def test_dump_roundtrip_preserves_fields(tmp_repo):
    from conftest import make_entry
    p = _write(tmp_repo, make_entry(title="A"))
    e = parse_entry(p)
    text = dump_entry(e)
    e2 = parse_entry(_write(tmp_repo, text))
    assert e2.fm["title"] == "A"


def test_non_mapping_frontmatter_treated_as_no_fm(tmp_repo):
    # YAML 根类型是 list 时不得抛 AttributeError, 与"无 front-matter"同路径:
    # fm={}, body=全文, 由 lint 自然报必填缺失
    text = "---\n- just\n- a\n- list\n---\n\n# 标题\n\n正文。\n"
    p = _write(tmp_repo, text)
    e = parse_entry(p)
    assert e.fm == {}
    assert "- just" in e.body and "# 标题" in e.body


def test_bom_tolerated(tmp_repo):
    """§31 实测: 带 BOM 的条目(Windows 记事本/PowerShell 存盘自带)曾让
    front-matter 正则不匹配 → index 静默跳过该条、search 永久不可见, 零告警。"""
    from conftest import SAMPLE_FRONTMATTER
    p = tmp_repo / "kb" / "pitfall" / "frontend" / "bom.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(SAMPLE_FRONTMATTER.encode("utf-8-sig"))
    e = parse_entry(p)
    assert e.fm.get("id") == "kb-20261012-7f3a"
    assert e.yaml_error is None


def test_broken_yaml_degrades_not_crashes(tmp_repo):
    """§31 实测: front-matter YAML 语法坏(人手缩进/tab)曾让 lint/index/stat 全库
    Traceback、search 静默空库。降级 fm={}+yaml_error, 调用方存活、坏文件可定位。"""
    text = "---\nid: x\ntitle: 坏: [a, b\n   broken: : :\n---\n\n# T\n"
    e = parse_entry(_write(tmp_repo, text))
    assert e.fm == {}
    assert e.yaml_error and "mapping values" in e.yaml_error


def test_list_fields_normalized_scalar_not_substring(tmp_repo):
    """§53 实锤: `domain: frontend`(标量)时 `"front" in "frontend"` 子串真——
    filter 假通过、related 截断 id 假命中、stat 把字符串拆成字母计数。
    parse 入口归一为单元素列表 + list_degraded 记录退化。"""
    text = ("---\nid: kb-20261011-aaaa\ntitle: t\ntype: pitfall\ndomain: frontend\n"
            "scope: project\nstatus: draft\nconfidence: speculative\n"
            "created: '2026-10-11'\nupdated: '2026-10-11'\n"
            "related: kb-20261011-zzzz\n---\n\n# T\n")
    e = parse_entry(_write(tmp_repo, text))
    assert e.fm["domain"] == ["frontend"]           # 标量 → 单元素列表
    assert e.fm["related"] == ["kb-20261011-zzzz"]
    assert len(e.list_degraded) == 2
    assert any("domain" in d for d in e.list_degraded)


def test_list_fields_null_and_dirty_elements(tmp_repo):
    """`tags:`(空→null)视作缺失(下游默认值生效); 列表内混入非字符串剔除。"""
    text = ("---\nid: kb-20261011-bbbb\ntitle: t\ntype: pitfall\ndomain: [frontend, 3, '']\n"
            "tags:\nscope: project\nstatus: draft\nconfidence: speculative\n"
            "created: '2026-10-11'\nupdated: '2026-10-11'\n---\n\n# T\n")
    e = parse_entry(_write(tmp_repo, text))
    assert "tags" not in e.fm                        # null → 缺失
    assert e.fm["domain"] == ["frontend"]            # 3 与 '' 被剔除
    assert len(e.list_degraded) == 2


def test_degraded_list_search_filter_exact_match(tmp_repo):
    """消费链端到端: 退化条目归一后, filter 只精确匹配, stat 不再字母分解。"""
    from kb import query, search as kb_search
    from kb.index import build_indexes
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.md").write_text(
        "---\nid: kb-20261011-aaaa\ntitle: 前端构建\ntype: pitfall\ndomain: frontend\n"
        "scope: project\nstatus: accepted\nconfidence: verified\nseverity: low\n"
        "created: '2026-10-11'\nupdated: '2026-10-11'\n---\n\n正文A\n", encoding="utf-8")
    build_indexes(tmp_repo, repo_name="docs")
    assert [r["id"] for r in kb_search.search(tmp_repo, domain="front")] == []
    assert [r["id"] for r in kb_search.search(tmp_repo, domain="frontend")] == ["kb-20261011-aaaa"]
    assert query.stat(tmp_repo)["by_domain"] == {"frontend": 1}


# ---- sections_text: 各 H2 段首句拼接(只供 index 匹配面, spec 4.2) -----------

def _sec_entry(tmp_path, name, body):
    """构造带正文的 Entry(_write 要求完整 front-matter, 这里只测正文派生)."""
    p = tmp_path / f"{name}.md"
    p.write_text("---\nid: kb-20261029-aaaa\ntitle: t\n---\n" + body, encoding="utf-8")
    return parse_entry(p)


def test_sections_text_joins_first_sentence_of_each_h2(tmp_path):
    """"每段首句"拼接: 六段式骨架下段首句即该病灶面主旨, 是 sections 匹配面的内容来源."""
    e = _sec_entry(tmp_path, "s1",
                   "# 标题\n\n## 根因\n启动期解析成功后上游 IP 漂移。围栏不参与。\n"
                   "```\n假首句 Vvvv。\n```\n\n## 解决方案\n"
                   "用 resolver 与 resolve 指令。第二段废话不该出现在结果里。\n")
    st = e.sections_text()
    assert "启动期解析成功后上游 IP 漂移" in st
    assert "resolver" in st
    assert "第二段废话" not in st          # 只取首句
    assert "假首句" not in st              # 围栏内容不作为首句来源


def test_sections_text_ascii_sentence_boundary_respects_dots(tmp_path):
    """句末 `.` 须后接空白且前一字符非数字才算终止; 版本号内的点(1.27.3)不得截断首句."""
    e = _sec_entry(tmp_path, "s2", "# t\n\n## 根因\nnginx 1.27.3 起支持 resolve。后续内容。\n")
    assert e.sections_text().startswith("nginx 1.27.3 起支持 resolve。")


def test_sections_text_caps_each_sentence_at_limit(tmp_path):
    e = _sec_entry(tmp_path, "s3", "# t\n\n## 根因\n" + "很长" * 100 + "\n")
    assert len(e.sections_text()) <= 60


def test_sections_text_empty_without_h2(tmp_path):
    """无 H2 段时返回空串(不抛): 派生面退化但 index 不因单条坏格式中断."""
    assert _sec_entry(tmp_path, "s4", "# t\n\n裸正文没有分段。\n").sections_text() == ""
