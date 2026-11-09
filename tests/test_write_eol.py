"""行尾回归: kb CLI 的产物必须是 LF。

Windows 上 `Path.write_text(text, encoding="utf-8")` 缺省 newline 会把 `\n` 翻成 CRLF,
而仓库里这些文件是 LF —— 于是每次 `kb index` / `kb review` 都把已跟踪文件重写成
CRLF, 表现为"`git status` 报修改但 `git diff` 零字节"的幻影 diff。本文件钉住:
写入方一律走 `write_text_lf`, 且产物字节里不出现 `\\r`。
"""
import datetime as dt
import pathlib
import re

from kb.fskit import write_text_lf
from kb.gate import create_draft, review
from kb.index import build_indexes
from conftest import make_entry

BODY = ("## 背景 / 现象\n现象一。\n\n## 根因\n行尾回归用根因文本。\n\n"
        "## 解决方案\n走 write_text_lf。\n")
SRC_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "kb"


def _assert_lf(p: pathlib.Path) -> None:
    assert b"\r" not in p.read_bytes(), f"{p.name} 含 CR, 行尾未被钉死为 LF"


def test_write_text_lf_pins_lf(tmp_path):
    p = tmp_path / "a.txt"
    write_text_lf(p, "a\r\nb\nc\r\n")          # 上游混入 CRLF 也要归一
    assert p.read_bytes() == b"a\nb\nc\n"


def test_index_artifacts_are_lf(tmp_repo):
    d = tmp_repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "x.md").write_bytes(make_entry(status="accepted",
                                        confidence="verified").encode())
    (d / "y.md").write_bytes(make_entry(id="kb-20261012-8888",
                                        title="draft 侧").encode())
    for _ in range(2):                          # 连写两遍: 幂等且不回写 CRLF
        build_indexes(tmp_repo)
        for name in ("INDEX.md", "index.jsonl", "index.draft.jsonl"):
            _assert_lf(tmp_repo / "kb" / name)


def test_entry_write_paths_are_lf(tmp_repo):
    e = create_draft(tmp_repo, type="pitfall", domain="frontend",
                     title="行尾回归", body=BODY, today=dt.date(2026, 11, 9))
    _assert_lf(e.path)
    review(tmp_repo, e.fm["id"], "proposed", today=dt.date(2026, 11, 9))
    _assert_lf(e.path)


def test_no_bare_write_text_in_src():
    """防回归: src/kb 下不得再出现绕过 write_text_lf 的裸 write_text。"""
    offenders = []
    for p in sorted(SRC_DIR.glob("*.py")):
        if p.name == "fskit.py":                # 唯一实现处
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.write_text\(", line):
                offenders.append(f"{p.name}:{n}: {line.strip()}")
    assert not offenders, "改用 kb.fskit.write_text_lf:\n" + "\n".join(offenders)
