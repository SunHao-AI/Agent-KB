import pathlib
from kb.entry import parse_entry
from kb.dedup import normalize, fingerprint_source, fingerprint

def _entry(tmp_path: pathlib.Path, body: str):
    p = tmp_path / "e.md"
    p.write_text("---\nid: kb-20261013-aaaa\ntitle: t\n---\n" + body, encoding="utf-8")
    return parse_entry(p)

def test_normalize_strips_case_space_punct():
    assert normalize("Vite, HMR:重启 失败!") == "vitehmr重启失败"

def test_root_cause_section_extracted(tmp_path):
    e = _entry(tmp_path, "# t\n\n## 背景 / 现象\n现象A\n\n## 根因\n机制 X, 说明 Y。\n\n## 解决方案\n改 Z\n")
    assert fingerprint_source(e) == "机制 X, 说明 Y。"

def test_no_root_cause_falls_back_to_body_without_h1(tmp_path):
    e = _entry(tmp_path, "# t\n\n前提: 装 node。\n步骤: 跑 npm i。\n")
    assert "装 node" in fingerprint_source(e) and "# t" not in fingerprint_source(e)

def test_fence_not_tricking_h2(tmp_path):
    e = _entry(tmp_path, "# t\n\n## 根因\n真根因。\n```\n## 根因\n围栏内假标题\n```\n尾行。\n")
    src = fingerprint_source(e)
    assert "围栏内假标题" in src  # 围栏内 ## 不终止采集

def test_fingerprint_stable_and_12hex(tmp_path):
    a_dir = tmp_path / "a"; a_dir.mkdir()
    b_dir = tmp_path / "b"; b_dir.mkdir()
    a = _entry(a_dir, "# t\n\n## 根因\n同一机制,同一结论。\n")
    b = _entry(b_dir, "# 不同标题\n\n## 根因\n同一机制   同一结论\n")
    assert fingerprint(a) == fingerprint(b)          # 规范化后等价
    assert len(fingerprint(a)) == 12
