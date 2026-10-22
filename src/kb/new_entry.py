from __future__ import annotations
import datetime as dt
import re
import secrets
from pathlib import Path
import yaml
from kb.taxonomy import load_taxonomy
from kb.entry import Entry, iter_entry_paths, parse_entry

_NONKEBAB = re.compile(r"[^a-z0-9]+")


def new_id(today: dt.date) -> str:
    return f"kb-{today.strftime('%Y%m%d')}-{secrets.token_hex(2)}"


def slug(title: str, today: dt.date) -> str:
    k = _NONKEBAB.sub("-", title.lower()).strip("-")
    return f"{today.isoformat()}-{k}" if k else today.isoformat()


def _unique_path(repo_root: Path, type_name: str, domain: str,
                 title: str, today: dt.date, entry_id: str) -> Path:
    base = slug(title, today)
    # kebab 部分为空(如纯中文标题)时用 id 后 4 hex 兜底, 避免同日同目录路径相同
    if base == today.isoformat():
        base = f"{base}-{entry_id[-4:]}"
    path = Path(repo_root) / "kb" / type_name / domain / f"{base}.md"
    n = 2
    while path.exists():
        path = path.with_name(f"{base}-{n}.md")
        n += 1
    return path


def _template_body(type_name: str) -> str:
    tax = load_taxonomy()
    sections = tax["types"][type_name]["sections"]
    return "\n".join(f"## {s}\n<!-- TODO -->\n" for s in sections)


def _existing_ids_for_day(repo_root: Path, today: dt.date) -> set[str]:
    """同日已占用的 id 集合(id 形如 kb-YYYYMMDD-xxxx, 只有日期段相同才可能撞)。
    按 **id 内容**而非文件名前缀筛: slug 允许人工改名而 id 不可变, 用文件名当
    日期代理会把改过名的同日条目漏出集合外——"同日 id 只与同日 id 撞"的前提
    成立, 不代表可以从文件名读出这个日期。new 是低频动作, 全量解析换正确性。"""
    marker = f"kb-{today.strftime('%Y%m%d')}-"
    ids = set()
    for p in iter_entry_paths(Path(repo_root)):
        try:
            eid = str(parse_entry(p).fm.get("id") or "")
        except Exception:  # noqa: BLE001 - 坏文件不该拦住新建, 交给 lint 报
            continue
        if eid.startswith(marker):
            ids.add(eid)
    return ids


def _unique_id(repo_root: Path, today: dt.date, taken: set[str]) -> str:
    """id 全仓唯一(第三十轮走查): 旧实现只给路径去重(_unique_path 的 -2 循环),
    id 直接落盘——4 hex 空间 65536, 同日 N 条按生日悖论 N=100 即约 7.6% 撞车。
    撞车后 _find 只命中第一个, 另一条 review/show/related/export 永久断链, 且
    写入瞬间零信号(静默), 只有事后 lint 才追溯。撞了换下一个随机值重试。"""
    for _ in range(64):
        candidate = new_id(today)
        if candidate not in taken:
            return candidate
    raise RuntimeError(
        f"cannot allocate unique id for {today}: 64 consecutive collisions, "
        f"同日条目数已逼近 id 空间上限(65536), 请检查是否有异常批量写入")


def create_entry(repo_root: Path, type: str, domain: str, scope: str,
                 title: str, generated: bool, today: dt.date) -> Entry:
    tax = load_taxonomy()
    if type not in tax["types"]:
        raise ValueError(f"unknown type: {type}")
    if domain not in tax["domains"]:
        raise ValueError(f"unknown domain: {domain}")
    fm = {
        "id": _unique_id(Path(repo_root), today, _existing_ids_for_day(Path(repo_root), today)),
        "title": title,
        "type": type,
        "domain": [domain],
        "tags": [],
        "scope": scope,
        "status": "draft" if generated else "proposed",
        "confidence": "speculative" if generated else "probable",
        "created": today.isoformat(),
        "updated": today.isoformat(),
    }
    if "severity" in tax["types"][type].get("requires", []):
        fm["severity"] = "medium"
    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    body = f"\n# {title}\n\n{_template_body(type)}"
    path = _unique_path(Path(repo_root), type, domain, title, today, fm["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_text}\n---\n{body}", encoding="utf-8")
    return parse_entry(path)
