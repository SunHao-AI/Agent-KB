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
