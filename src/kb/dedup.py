from __future__ import annotations
import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:      # 纯注解用途(本模块无 Entry 运行时使用); 让 entry 可反向导入 h2_sections
    from kb.entry import Entry

# 规范化删除的标点集(中英文, 固定不可配置, spec §4)
_PUNCT = (
    ",.;:!?\"'`()[]{}<>`~@#$%^&*-_=+/\\|"
    "，。、；：！？“”‘’（）《》【】〔〕「」『』…—～·〈〉"
)
_STRIP_RE = re.compile(f"[{re.escape(_PUNCT)}\\s]")


def normalize(text: str) -> str:
    return _STRIP_RE.sub("", text.lower())


def h2_sections(entry: Entry) -> list[tuple[str, str]]:
    """正文所有 H2 段的 (段名, 段内容) 列表; 围栏代码块内 '## ' 开头行不算标题."""
    sections: list[tuple[str, str]] = []
    header: str | None = None
    buf: list[str] = []
    in_fence = False
    for ln in entry.body.splitlines():
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            if header is not None:
                buf.append(ln)
            continue
        if not in_fence and ln.startswith("## "):
            if header is not None:
                sections.append((header, "\n".join(buf).strip()))
            header = ln[3:].strip()
            buf = []
            continue
        if header is not None:
            buf.append(ln)
    if header is not None:
        sections.append((header, "\n".join(buf).strip()))
    return sections


def fingerprint_source(entry: Entry) -> str:
    """第一个段名含'根因'的 H2 段全文; 无根因段则退化正文全文(剔 H1 行)."""
    for header, content in h2_sections(entry):
        if "根因" in header:
            return content
    lines = entry.body.splitlines()
    return "\n".join(ln for ln in lines if not ln.strip().startswith("# ")).strip()


# 规范化源短于该长度不参检(防测试桩/占位段互撞)。唯一事实源, lint 侧 import 复用
MIN_FP_LEN = 16
_MIN_FP_LEN = MIN_FP_LEN  # 内部旧名别名(兼容既有引用), 勿再新增使用点


def fingerprint_text(text: str) -> str:
    """规范化文本指纹(12 位小写 hex); 规范化源短于 MIN_FP_LEN 返回 ''."""
    src = normalize(text)
    if len(src) < MIN_FP_LEN:
        return ""
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


def fingerprint(entry: Entry) -> str:
    """条目指纹, 恒为 12 hex(index dedup_key 依赖, 短源也出值)."""
    src = normalize(fingerprint_source(entry))
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]
