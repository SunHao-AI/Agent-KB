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
