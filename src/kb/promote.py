from __future__ import annotations
import datetime as dt
from kb.entry import parse_entry
from kb.gate import _find, _save, set_scope


def promote(repo_root, id: str, to: str, today: dt.date | None = None) -> dict:
    """人工 CLI: 上提 scope 并打 promoted tag(建议标记).

    scope 变更与 needs-scope-review 清理复用 gate.set_scope 公共写路径,
    本函数只做 stack/universal 目标限制与 promoted tag 追加, 不再独立写 scope。
    """
    if to not in ("stack", "universal"):
        raise ValueError(f"promote target scope must be stack/universal, got {to}")
    today = today or dt.date.today()
    e = set_scope(repo_root, id, to, today=today)  # 枚举校验 + 标签清理 + 落盘
    p = _find(repo_root, id)
    fm = dict(e.fm)
    tags = list(fm.get("tags") or [])
    if "promoted" not in tags:
        tags.append("promoted")
    fm["tags"] = tags
    _save(p, fm, e.body, today)
    return parse_entry(p).fm
