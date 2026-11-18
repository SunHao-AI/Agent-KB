"""通用层 submodule 的同步: 只读提醒(`lag_notice`) + 唯一写路径(`plan_sync`/`apply_sync`)。

为什么需要它(kb-20261101-8321, accepted/verified): 四仓经 `.agent-kb` submodule 挂载
通用知识库, 生成物 `kb/index.jsonl` 是 git 跟踪文件 —— 指针停在旧提交, 工作树拿到的
就是旧生成物, `sections` 检索面整层失效(实测召回降至 44%)。而三道防线各有缺口:
`kb index` 只重建被写的仓; `kb index --check` 只在 kb 正文变更的 push 上触发(推指针
不触发); `kb doctor` 有检查但既不 fetch 也没人主动跑。本模块补的是"发现 + 推进"的
最后一公里。

分工: 提醒在 search(CLI/MCP), 只读零网络; fetch/checkout/commit 全部集中在本模块,
且**永不 push**。
"""
from __future__ import annotations

import os
from pathlib import Path

from kb.bootstrap import (_biz_root, _git_out,  # noqa: F401 - _git_out 供本模块
                          _submodule_branch, kb_corpus_lag)  # Task 4 写路径复用


def _declared_branch(biz: Path) -> str | None:
    """.gitmodules 里 .agent-kb 的跟踪分支; 未声明 .agent-kb 时返回 None。"""
    gm = biz / ".gitmodules"
    if not gm.exists() or ".agent-kb" not in gm.read_text(encoding="utf-8",
                                                          errors="replace"):
        return None
    return _submodule_branch(gm)


def lag_notice(biz_root: Path, branch: str | None = None) -> str | None:
    """检索侧一行提醒 → 有语料漂移返回文本, 否则 **None**(绝不返回空串)。

    零网络、零写入, 任何异常路径一律回 None: 检索是本仓最高频入口(近 7 天 L2 事件
    131 次, 日均约 19), 提醒的失败模式必须是"当作没有", 而不是把 search 一起带崩。

    文案自带时效声明: 离线口径算的是 origin/<branch> 的上次 fetch 快照, 真实漂移
    只会更多(setting 实测真实 7 / 离线可见 1)。
    """
    if os.environ.get("KB_NO_LAG_HINT"):
        return None
    biz = _biz_root(Path(biz_root))
    br = branch if branch is not None else _declared_branch(biz)
    if br is None:
        return None
    sub = biz / ".agent-kb"
    if not (sub / "kb").is_dir():          # 未 init: 归 doctor 的悬空指针项管
        return None
    lag, ref = kb_corpus_lag(sub, br)      # 模块顶层 import: 供测试统一打桩
    if not lag:                            # 0 与 None 都不出声
        return None
    return (f"[kb] 通用层落后 {lag} 个语料提交(参照 {ref}, 上次 fetch 快照"
            f"可能更少) → kb sync")
