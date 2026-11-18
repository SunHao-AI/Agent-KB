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
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from kb.bootstrap import _biz_root, _git_out, _submodule_branch, kb_corpus_lag


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


def _run(args: list[str]) -> tuple[int, str, str]:
    """执行 git 写命令 → (returncode, stdout, stderr)。

    与 `_git_out`(只读、吞错)分开: 写路径必须把 stderr 原样交给调用方呈现,
    否则 commit 被 hook 拒时人只能看到"失败了"。

    超时/OS 错误吞成 (124, ...) 而非穿透: `fetch` 是本模块唯一网络调用, 挂死
    >120s 若抛 TimeoutExpired 就绕过 fetch-failed 分支, 人只看到裸 traceback。
    走 (rc, out, err) 契约则既有失败路径(fetch-failed 等)原样接住。
    """
    try:
        r = subprocess.run(["git", *args], check=False, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, "", f"命令超时/失败: git {' '.join(args[:3])} …: {exc}"
    return r.returncode, r.stdout.strip(), r.stderr.strip()


@dataclass
class SyncPlan:
    declared: bool = False
    branch: str | None = None
    sub: Path | None = None
    head: str = ""
    tip: str = ""
    lag: int = 0
    raw_lag: int = 0
    corpus_log: str = ""
    dirty: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    # 机器可读拒绝码(§4.4): 每个拒绝案例一个稳定码, reasons 只做人读文案。
    # 两个拒绝案例不得共用同一个码, 否则脚本消费方分不开场景。
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.declared and not self.reasons


def plan_sync(biz_root: Path) -> SyncPlan:
    """只读勘察: 该不该同步、会被纳入什么。不 fetch 不写, 可反复跑。"""
    biz = _biz_root(Path(biz_root))
    plan = SyncPlan(sub=biz / ".agent-kb")
    plan.branch = _declared_branch(biz)
    if plan.branch is None:
        plan.reasons.append("not-a-submodule-repo")
        plan.code = "not-a-submodule-repo"
        return plan
    plan.declared = True
    if not (plan.sub / "kb").is_dir():
        # 码与文案分工: code 供机器分场景, 文案是**全模块唯一**一处 init 指引
        # (spec §4.4; 检索侧零 init 提示由 Task 3 用例守护)。
        plan.reasons.append("submodule 未初始化: git submodule update --init .agent-kb")
        plan.code = "submodule-not-initialized"
        return plan
    plan.head = _git_out(["-C", str(plan.sub), "rev-parse", "HEAD"]) or ""
    plan.tip = _git_out(["-C", str(plan.sub), "rev-parse", "--verify",
                         f"origin/{plan.branch}"]) or ""
    if not plan.tip:
        plan.reasons.append(f"无 origin/{plan.branch} 引用(需先 fetch)")
        plan.code = "origin-ref-missing"
        return plan
    _rc, out, _err = _run(["-C", str(plan.sub), "status", "--porcelain"])
    plan.dirty = [ln[3:] for ln in out.splitlines() if ln.strip()]
    if plan.dirty:
        plan.reasons.append("dirty-submodule")
        plan.code = "dirty-submodule"
        return plan
    plan.lag = kb_corpus_lag(plan.sub, plan.branch)[0] or 0
    plan.raw_lag = int(_git_out(["-C", str(plan.sub), "rev-list", "--count",
                                 f"HEAD..{plan.tip}"]) or 0)
    plan.corpus_log = _git_out(["-C", str(plan.sub), "log", "--oneline",
                               f"HEAD..{plan.tip}", "--", "kb/"]) or ""
    return plan


@dataclass
class SyncResult:
    ok: bool
    code: str
    detail: str = ""
    commit_sha: str | None = None

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _indexes_fresh(sub: Path) -> bool:
    """tip 自带的生成物索引是否与正文一致 —— 本模块存在的技术要害。

    `kb/index.jsonl` 是 git 跟踪文件, 指针指向自带旧索引的 tip 就会让 `sections`
    检索面整层失效(kb-20261101-8321 的根因第 1+3 条)。就地重建无效(submodule
    update 即丢弃), 唯一持久化方式是推进指针 —— 那就必须保证推进的目标本身健康。
    这一步使该缺陷**结构性不可复发**。
    """
    from kb.index import check_indexes, resolve_repo_name
    try:
        return check_indexes(sub, repo_name=resolve_repo_name(sub))
    except (FileNotFoundError, OSError):
        return False


def apply_sync(biz_root: Path) -> SyncResult:
    """fetch → checkout tip → 校验索引新鲜 → 只提交 gitlink。**永不 push**。"""
    biz = _biz_root(Path(biz_root))
    plan = plan_sync(biz)
    if not plan.declared:
        return SyncResult(False, "not-a-submodule-repo",
                          "本仓 .gitmodules 未声明 .agent-kb, 无指针可同步。")
    if plan.reasons and "dirty-submodule" in plan.reasons:
        return SyncResult(False, plan.code,
                          ".agent-kb 有未提交改动, 先在其中提交或 stash: \n  "
                          + "\n  ".join(plan.dirty))
    if plan.reasons:
        # 每个拒绝案例带各自的稳定码(submodule-not-initialized /
        # origin-ref-missing / ...), 不再压成泛化 "precondition" ——
        # 机器消费方要能分辨场景(§4.4)。
        return SyncResult(False, plan.code, "\n".join(plan.reasons))

    rc, _out, err = _run(["-C", str(plan.sub), "fetch", "origin", plan.branch])
    if rc != 0:
        return SyncResult(False, "fetch-failed",
                          f"git fetch 失败, 未产生任何写入:\n{err}")
    tip = _git_out(["-C", str(plan.sub), "rev-parse", "FETCH_HEAD"]) or ""
    if not tip:
        return SyncResult(False, "fetch-failed", "FETCH_HEAD 不可解析, 未产生任何写入。")
    plan.tip = tip
    # None 与 0 是两回事: 0 = 算过且不落后, None = 探针本身失败(损坏对象 / 与每日
    # traces 定时任务抢 index.lock, §4.4 明写的场景)。`or 0` 把两者压平 → 探针一抖
    # 就 up-to-date + exit 0, 是本模块要消灭的虚假成功。
    lag = kb_corpus_lag(plan.sub, plan.branch)[0]
    if lag is None:
        return SyncResult(False, "corpus-lag-unknown",
                          "fetch 后仍无法计算语料 lag(探针失败), 未产生任何写入;"
                          " 请稍后重试或人工核对 .agent-kb 仓状态。")
    plan.lag = lag
    if plan.lag == 0:
        # 原始数取 fetch 后口径: plan.raw_lag 是勘察(fetch 前)算的, 用它打 fetch 后
        # 的"已最新"文案会在捞出 50 个提交后仍写"原始 0 个"。
        plan.raw_lag = int(_git_out(["-C", str(plan.sub), "rev-list", "--count",
                                     f"HEAD..{tip}"]) or plan.raw_lag)
        return SyncResult(True, "up-to-date",
                          f"语料已最新(原始 {plan.raw_lag} 个提交, 均不触及 kb/)。")

    rc, _out, err = _run(["-C", str(plan.sub), "checkout", "--detach", tip])
    if rc != 0:
        # 半切换态如实报, 不自动 `checkout -- .`: 那会吞掉他人可能正在做的
        # submodule 操作。本函数保证自己的每一步可重放, 不负责收拾现场。
        return SyncResult(False, "checkout-failed",
                          f"checkout {tip[:7]} 失败(工作树可能处于中间态, 请人工确认):\n{err}")

    if not _indexes_fresh(plan.sub):
        rb_rc, _rb_out, rb_err = _run(
            ["-C", str(plan.sub), "checkout", "--detach", plan.head])
        if rb_rc != 0:
            # 回滚失败必须如实报(§4.3 错误教义): 此刻 submodule 实际仍停在被拒的
            # tip 上, 声称"已回滚"是在对仓库状态撒谎; 把人工命令原样给出。
            return SyncResult(False, "tip-index-stale",
                              (f"tip {tip[:7]} 自带的 kb/index.jsonl 与正文不一致, "
                               f"且回滚 checkout 失败, submodule 可能仍停在 tip "
                               f"{tip[:7]}(未提交任何 gitlink):\n{rb_err}\n"
                               f"请人工执行 `git -C .agent-kb checkout --detach "
                               f"{plan.head}`, 再在 Agent-KB 主仓跑 "
                               f"`kb index --repo . --repo-name agent-kb` 并提交。"))
        return SyncResult(False, "tip-index-stale",
                          (f"tip {tip[:7]} 自带的 kb/index.jsonl 与正文不一致, "
                           f"已回滚到 {plan.head[:7]}。请在 Agent-KB 主仓跑 "
                           f"`kb index --repo . --repo-name agent-kb` 并提交。"))

    rc, _out, err = _run(["-C", str(biz), "commit", "--only", ".agent-kb",
                          "-m", f"chore(kb): bump .agent-kb -> {tip[:7]}"])
    if rc != 0:
        return SyncResult(False, "commit-failed",
                          f"提交失败(submodule 已在新 tip, 重跑幂等):\n{err}")
    sha = _git_out(["-C", str(biz), "rev-parse", "HEAD"])
    return SyncResult(True, "bumped",
                      f"已推进指针 {plan.head[:7]} → {tip[:7]}(语料 {plan.lag} 个提交)。"
                      f"未 push。", sha)


def render_plan(plan: SyncPlan) -> str:
    lines = [f"仓库指针   {plan.head[:7] or '—'}"]
    if not plan.declared:
        lines.append("结论: 本仓未声明 .agent-kb submodule, 无指针可同步。")
        return "\n".join(lines)
    lines.append(f"跟踪分支   {plan.branch}")
    lines.append(f"origin 引用 {plan.tip[:7] or '—'}(上次 fetch 快照)")
    lines.append(f"语料落后   {plan.lag} 个提交(原始 {plan.raw_lag}, 差额在 src/kb/ 与 traces/)")
    if plan.reasons:
        lines.append("不可同步: " + "; ".join(plan.reasons))
        if plan.dirty:
            lines.append("  脏文件: " + ", ".join(plan.dirty))
        return "\n".join(lines)
    if plan.lag == 0:
        lines.append("结论: 语料已最新, 无需同步。")
        return "\n".join(lines)
    lines.append("将被纳入的语料提交:")
    lines.extend(f"  {ln}" for ln in plan.corpus_log.splitlines() if ln.strip())
    lines.append("下一步: kb sync --apply")
    return "\n".join(lines)


def render_result(res: SyncResult) -> str:
    head = f"[{'ok' if res.ok else 'FAIL'}] {res.code}"
    return f"{head}\n{res.detail}" if res.detail else head
