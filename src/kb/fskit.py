"""统一文本写入口: 钉死 LF 行尾。

Windows 上 `Path.write_text(text, encoding="utf-8")` 未传 `newline` 时走 Python 默认
translate 模式, 会把 `\n` 翻成 `os.linesep`(即 `\r\n`)。kb CLI 的产物(index 生成物、
条目正文、骨架等)在仓库里是 LF, 于是每次 `kb index` / `kb review` 都把已跟踪文件
重写成 CRLF —— `git status` 报修改、`git diff` 零字节(仓库有 `.gitattributes` 的
`text eol=lf`, clean 过滤器擦回 LF 后 blob 与 HEAD 同哈希), 形成"整文件幻影 diff"。

故所有文本写入一律走本函数, 不要直接 `write_text`。
"""
from __future__ import annotations

from pathlib import Path


def write_text_lf(path: Path, text: str) -> None:
    """写文本文件并保证行尾为 LF(与调用方所在平台无关)。

    两道保险: `newline="\n"` 关闭换行翻译; `replace` 兜住上游字符串本身混入的 CRLF。
    """
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
