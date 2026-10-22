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
    yaml_error: str | None = None   # front-matter YAML 语法错误原文(第十三轮走查)

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
    # utf-8-sig: 容忍 BOM(Windows 记事本/PowerShell Set-Content 存盘自带)。
    # BOM 留在文首会让 front-matter 正则不匹配 → 条目被 index 静默跳过、
    # search 不可见(第十三轮走查实测); 对无 BOM 文件行为不变。
    text = pathlib.Path(path).read_text(encoding="utf-8-sig")
    m = _FM_RE.match(text)
    if not m:
        return Entry(fm={}, body=text, path=pathlib.Path(path))
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        # 人手编辑的 front-matter 语法坏(缩进/tab/未闭合流)曾让 lint/index/stat 全库
        # Traceback、search 静默空库(坏文件挡住 index 重建后)。降级 fm={} 保调用方
        # 存活: 坏文件按"缺必填"被 lint 报出(精确消息见 lint_repo), 其余条目照常。
        return Entry(fm={}, body=text, path=pathlib.Path(path),
                     yaml_error=str(exc).replace("\n", " ")[:200])
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


# kb 根生成物固定名, 不作为条目(唯一事实源; lint/index/gate/query 共用)
GENERATED_NAMES = {"INDEX.md", "index.jsonl", "index.draft.jsonl"}


def iter_entry_paths(repo_root) -> list[pathlib.Path]:
    """条目文件发现的**唯一**规则(第二十四轮走查 §42)。

    布局契约: 条目只住在 kb/<第一层目录=type>/<...>/<slug>.md; 点开头目录是
    挂载的外仓(有自己的 kb 根和 lint), 不进父仓视野。

    修复前 index/gate/query 用 `kb.rglob("*.md")` 全量扫, lint 却只走第一层目录
    ——两套定义漂移出"kb 根直下散文件进 index(可被检索消费)却逃过 lint 全部
    校验"的免检角落(坏 type/坏 status 照样进检索)。所有读写方一律走本函数,
    契约漂移在结构上不可能; 契约外的带 id 散文件由 lint 显式报错(见 stray)。
    """
    kb = pathlib.Path(repo_root) / "kb"
    if not kb.exists():
        return []
    out: list[pathlib.Path] = []
    for d in sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for p in sorted(d.rglob("*.md")):
            if p.name in GENERATED_NAMES:
                continue
            out.append(p)
    return out


def stray_entry_paths(repo_root) -> list[pathlib.Path]:
    """布局契约外的"散落条目": kb 根直下的 *.md(非生成物)且带可解析 front-matter
    id。它们被 iter_entry_paths 排除在检索外, 但带 id 说明是手滑放错位置的条目
    (静默不可见比报错更糟), 由 lint 显式报出。只查 kb 根一层, 不下探点目录
    (外仓自管)。
    """
    kb = pathlib.Path(repo_root) / "kb"
    if not kb.exists():
        return []
    return [p for p in sorted(kb.glob("*.md"))
            if p.name not in GENERATED_NAMES and parse_entry(p).fm.get("id")]
