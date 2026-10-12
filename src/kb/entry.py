from __future__ import annotations
import datetime as _dt
import pathlib
import re
from dataclasses import dataclass
import yaml

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _normalize_dates(fm: dict) -> dict:
    # YAML 会把未加引号的 2026-10-12 解析成 datetime.date; schema 要求 str, 统一归一为 ISO 字符串
    for k, v in fm.items():
        if isinstance(v, _dt.datetime):
            fm[k] = v.date().isoformat()
        elif isinstance(v, _dt.date):
            fm[k] = v.isoformat()
    return fm


@dataclass
class Entry:
    fm: dict
    body: str
    path: pathlib.Path

    def h1(self) -> str | None:
        for line in self.body.splitlines():
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip()
        return None

    def summary(self, limit: int = 120) -> str:
        # 按空行分块, 块内剔除标题行(标题可能与正文同块), 取第一个还有正文的块
        for block in re.split(r"\n\s*\n", self.body):
            lines = [ln for ln in block.splitlines() if not ln.strip().startswith("#")]
            b = re.sub(r"\s+", " ", " ".join(lines)).strip()
            if b:
                return b[:limit]
        return ""


def parse_entry(path: pathlib.Path) -> Entry:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        return Entry(fm={}, body=text, path=pathlib.Path(path))
    data = yaml.safe_load(m.group(1))
    # YAML 根类型非 mapping(list/str/...)视为无 front-matter: fm={}, body=全文,
    # 由 lint 自然报必填缺失, 避免 _normalize_dates 对 list 抛 AttributeError
    if not isinstance(data, dict):
        return Entry(fm={}, body=text, path=pathlib.Path(path))
    fm = _normalize_dates(data)
    body = m.group(2)
    return Entry(fm=fm, body=body, path=pathlib.Path(path))


def dump_entry(entry: Entry) -> str:
    fm_text = yaml.safe_dump(entry.fm, allow_unicode=True, sort_keys=False).strip()
    body = entry.body if entry.body.startswith("\n") else "\n" + entry.body
    return f"---\n{fm_text}\n---\n{body}"
