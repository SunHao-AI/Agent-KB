from __future__ import annotations
import datetime as dt
from kb.entry import parse_entry
from kb.gate import _find, _save

# 建议标签: `promoted` 标记"已被建议上提", `promote-to:<scope>` 记录建议目标。
# 用 tags 承载(而非新 front-matter 字段): tags 是 schema 自由数组, 不动派生 schema。
PROMOTE_TAG = "promoted"


def promote(repo_root, id: str, to: str, today: dt.date | None = None) -> dict:
    """人工 CLI: 标记"建议上提 scope"——只打建议标签, **不改 scope**。

    第二十一轮走查(§39): 四处文档一致定义 promote 为纯建议(AGENTS.md 红线2"只做
    建议, 由人 set-scope/export 落地"、README §4、spec §9 终审工作流、测试设定 C12
    "加 needs-scope-review 建议, 不改 scope")。旧实现复用 set_scope 立即改 scope +
    清 needs-scope-review——等于把刚发出的建议从人工待办清单(--needs-scope)抹掉,
    还造成 scope 与物理位置错位(标 stack 却躺在项目仓, 双层检索按 scope 过滤即错层)。
    人工终审落地仍是 gate.set_scope / export_entry(它们消费并清掉建议标签)。
    """
    if to not in ("stack", "universal"):
        raise ValueError(f"promote target scope must be stack/universal, got {to}")
    today = today or dt.date.today()
    p = _find(repo_root, id)
    e = parse_entry(p)
    fm = dict(e.fm)
    # 重复 promote 视为改判目标: 旧 promote-to:* 被替换, 不堆积
    tags = [t for t in (fm.get("tags") or [])
            if not str(t).startswith("promote-to:")]
    tags.append(f"promote-to:{to}")
    if "needs-scope-review" not in tags:
        tags.append("needs-scope-review")  # 进入/留在人工终审待办清单
    if PROMOTE_TAG not in tags:
        tags.append(PROMOTE_TAG)
    fm["tags"] = tags
    _save(p, fm, e.body, today)
    return parse_entry(p).fm
