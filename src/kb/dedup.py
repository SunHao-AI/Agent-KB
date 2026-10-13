from __future__ import annotations
import hashlib
import re
from kb.entry import Entry

# 规范化删除的标点集(中英文, 固定不可配置, spec §4)
_PUNCT = (
    ",.;:!?\"'`()[]{}<>`~@#$%^&*-_=+/\\|"
    "，。、；：！？“”‘’（）《》【】〔〕「」『』…—～·〈〉"
)
_STRIP_RE = re.compile(f"[{re.escape(_PUNCT)}\\s]")


def normalize(text: str) -> str:
    return _STRIP_RE.sub("", text.lower())


def fingerprint_source(entry: Entry) -> str:
    """第一个 H2 含'根因'的段全文; 无根因段则退化正文全文(剔 H1 行)."""
    out: list[str] = []
    capturing = False
    in_fence = False
    lines = entry.body.splitlines()
    for ln in lines:
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            if capturing:
                out.append(ln)
            continue
        if not in_fence and ln.startswith("## "):
            if capturing:
                break
            if "根因" in ln:
                capturing = True
            continue
        if capturing:
            out.append(ln)
    if capturing:
        return "\n".join(out).strip()
    return "\n".join(ln for ln in lines if not ln.strip().startswith("# ")).strip()


def fingerprint(entry: Entry) -> str:
    src = normalize(fingerprint_source(entry))
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]
