"""B1 接入体验: `kb init` 生成去绝对路径的 .mcp.json; `kb doctor` 环境自检。

.mcp.json 的 command 用相对 Agent-KB 根的标志性解释器路径(`.venv/bin/python`
或 `.venv/Scripts/python.exe`), 运行时由 Agent 侧结合 `"cwd": "<Agent-KB 根>"`
解析 —— 换机器/换克隆位置不必改配置(roadmap B1: 去绝对路径)。

doctor 检查项吸收 A6 门禁自检口径(母本 scripts/pre-push-gate.sh §0 环境自检 +
执行包 §6): venv 存在 / 缺 pytest / 缺 ruff / pytest-cov 降级; 另加 submodule
悬空 / index 漂移 / kb lint / 已装 pre-push 门禁新鲜度 / .mcp.json 可解析。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

INTERPRETERS = (".venv/bin/python", ".venv/Scripts/python.exe")


def _agent_kb_root(repo: Path, agent_kb: Path | None = None) -> Path:
    """Agent-KB 主仓根定位: 候选 = [显式 --agent-kb, 业务仓自身, 同级克隆
    repo/../Agent-KB]。须自证 src/kb 包存在; 其中优先带 venv 的(主仓约定 venv
    在根; submodule 检出 .agent-kb 同样自证但不带 venv, 落选)。都不中回退 repo。"""
    repo = Path(repo)
    biz = _biz_root(repo)
    cands = [Path(agent_kb)] if agent_kb is not None else []
    cands += [biz, biz.resolve().parent / "Agent-KB"]
    cands = [c for c in cands if (c / "src" / "kb").exists()]
    for c in cands:
        if resolve_interpreter(c):
            return c
    return cands[0] if cands else repo


def _git_root(p: Path) -> Path | None:
    """git 仓根(业务仓根): doctor 用它区分 kb 载体目录(--repo docs)与仓根(.git/
    .venv/.mcp.json/.gitmodules 所在)。非 git 环境回退 None。"""
    try:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"],
                           check=False, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return Path(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def resolve_interpreter(root: Path) -> str | None:
    root = Path(root)
    for rel in INTERPRETERS:
        if (root / rel).exists():
            return rel
    return None


def render_mcp_json(repo_name: str, kb_dir: str, agent_kb_rel: str | None,
                    interpreter_rel: str, mcp_name: str = "kb") -> str:
    # repo 字段规范名统一小写(同 index 口径), 防大小写漂移致检索 caller_repo 对不上。
    # 不写 cwd: 客户端默认 cwd = .mcp.json 所在目录(业务仓根), args 里的相对
    # --repo/--agent-kb 即按此解析; command 写仓根相对的 venv 解释器路径
    # (同级克隆约定下形如 ../Agent-KB/.venv/...), 跨机可移植且直接可执行。
    args = ["-m", "kb.mcp", "--repo", kb_dir]
    if agent_kb_rel:
        args += ["--agent-kb", agent_kb_rel]
    args += ["--repo-name", repo_name.lower()]
    payload = {
        "mcpServers": {
            mcp_name: {
                "command": interpreter_rel,
                "args": args,
            }
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _biz_root(kb_base: Path) -> Path:
    """业务仓根(写 .mcp.json、放 .git/.venv 的目录)。kb_base = kb 载体目录
    (与 lint/index/doctor 的 --repo 约定一致: 业务仓即 docs/、Agent-KB 仓即仓根)。"""
    kb_base = Path(kb_base)
    g = _git_root(kb_base)
    if g:
        return g
    return kb_base if (kb_base / ".git").exists() or not (kb_base / "kb").is_dir() \
        else kb_base.parent


def init_repo(kb_base: Path, agent_kb: Path | None, kb_dir: str,
              repo_name: str | None = None, mcp_name: str = "kb",
              force: bool = False) -> dict:
    """写入接入仓 .mcp.json 并返回引导信息(下一步指引由调用方打印)。

    `kb_base` = kb 载体目录(同 doctor); 业务仓根经 git toplevel 推导。
    首次接入友好: kb_dir 不存在则创建骨架(可直接 `kb new`); 仓内无 .agent-kb
    submodule 时生成单层配置(不挂 --agent-kb), 提示可后补 submodule。
    """
    kb_base = Path(kb_base)
    repo = _biz_root(kb_base)
    root = _agent_kb_root(kb_base, agent_kb)
    interp = resolve_interpreter(root)
    if interp is None:
        raise FileNotFoundError(
            f"Agent-KB venv 未装配: {root} 下无 {' / '.join(INTERPRETERS)} "
            f"(先建 venv 并 pip install -e .)")
    created = False
    if not (repo / kb_dir / "kb").is_dir():
        # lint/index 的遍历约定是 <kb载体>/kb/<type>/...; 缺 kb/ 时补骨架
        (repo / kb_dir / "kb").mkdir(parents=True, exist_ok=True)
        created = True
    ak = Path(agent_kb) if agent_kb else repo / ".agent-kb"
    ak_rel: str | None = None
    if ak.exists():
        try:
            ak_rel = ak.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            if agent_kb is not None:  # 显式指定的必须在仓内(要写进相对 args)
                raise FileNotFoundError(
                    f"--agent-kb 必须位于接入仓内(写进 .mcp.json 的相对 args): {ak}") from None
            ak_rel = None  # 仓外的 Agent-KB: 不作为 submodule 相对路径写入
    elif agent_kb is not None:
        raise FileNotFoundError(f"--agent-kb 不存在(先 git submodule update --init): {ak}")
    # 未显式指定且缺省位置不存在 = 尚未挂 submodule → 单层降级
    # command 必须相对仓根(.mcp.json 所在目录 = 客户端默认 cwd)可直接执行
    cmd_rel = Path(os.path.relpath(root.resolve() / interp,
                                   repo.resolve())).as_posix()
    out = repo / ".mcp.json"
    if out.exists() and not force:
        raise FileExistsError(f"{out} 已存在(覆盖请加 --force)")
    name = (repo_name or repo.resolve().name).lower()
    out.write_text(render_mcp_json(name, kb_dir, ak_rel, cmd_rel, mcp_name),
                   encoding="utf-8")
    return {"mcp_json": str(out), "agent_kb_root": str(root),
            "command": cmd_rel, "repo_name": name,
            "layered": ak_rel is not None, "kb_dir_created": created}


# ---------------- doctor ----------------

def _mod_ok(root: Path, interp: str, mod: str) -> bool:
    try:
        r = subprocess.run([str(root / interp), "-c", f"import {mod}"],
                           check=False, capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_uv_venv(venv_root: Path) -> bool:
    """uv 创建的 venv 默认不 bootstrap pip(pyvenv.cfg 带 `uv = <ver>` 行),
    装包必须走 `uv pip install --python`; 给 pip 命令会把人引向死路。"""
    cfg = Path(venv_root) / ".venv" / "pyvenv.cfg"
    if not cfg.exists():
        return False
    return "uv" in cfg.read_text(encoding="utf-8", errors="replace")


def _install_cmd(venv_root: Path, interp: str, pkgs: str) -> str:
    """缺失依赖的装包命令, 按 venv 装配通道(uv/标准)给出可直接复制的形态。"""
    py = (Path(venv_root) / interp).as_posix()
    if _is_uv_venv(venv_root):
        return f"uv pip install {pkgs} --python {py}"
    return f"{py} -m pip install {pkgs}"


def doctor(repo: Path, agent_kb: Path | None = None,
           current_python: bool = False) -> list[tuple[str, str, str]]:
    """返回 [(级别, 检查名, 说明)]; 级别 ∈ PASS/WARN/FAIL。永不抛异常。

    `repo` = kb 载体目录(与 lint/index 的 --repo 约定一致: 其下有 kb/), 业务仓
    即 docs/、Agent-KB 仓自身即仓根; 业务仓根(钩子/.venv/.mcp.json/.gitmodules
    所在)经 git toplevel 解析。
    """
    from kb.index import check_indexes
    from kb.lint import lint_repo

    checks: list[tuple[str, str, str]] = []
    kb_base = Path(repo)
    add = checks.append

    biz = _biz_root(kb_base)
    is_agent_kb_repo = biz.resolve() == kb_base.resolve()
    root = _agent_kb_root(kb_base, Path(agent_kb) if agent_kb else None)

    interp = resolve_interpreter(root)
    if interp:
        add(("PASS", "agent-kb venv (mcp)", f"{root} → {interp}"))
    else:
        add(("FAIL", "agent-kb venv (mcp)",
             f"{root} 缺 venv(.venv/bin/python 或 .venv/Scripts/python.exe)"))

    # 门禁环境 = 业务仓自身 .venv(A6 pre-push 就地跑 pytest/ruff 用的那套)
    ginterp = resolve_interpreter(biz) or (interp if is_agent_kb_repo else None)
    gate_root = biz if resolve_interpreter(biz) else (root if is_agent_kb_repo else biz)
    if ginterp:
        dev = _install_cmd(gate_root, ginterp, "-e '.[dev]'") \
            if gate_root.resolve() == root.resolve() \
            else _install_cmd(gate_root, ginterp, "pytest ruff pytest-cov")
        for mod, lvl, why in (("pytest", "FAIL", "门禁硬依赖"),
                              ("ruff", "WARN", "门禁 lint 依赖, 缺失时 lint 环节降级"),
                              ("pytest_cov", "WARN", "coverage 报告降级(非门禁项)")):
            ok = _mod_ok(gate_root, ginterp, mod)
            add((("PASS" if ok else lvl), f"gate {mod}",
                 "ok" if ok else f"{why}; 补装: {dev}"))
    else:
        add(("FAIL", "gate venv", f"{biz} 缺 .venv, 门禁无法运行"))

    if current_python:
        add(("PASS", "current interpreter", sys.executable))
        for mod in ("pytest", "ruff", "pytest_cov"):
            try:
                __import__(mod)
                add(("PASS", f"current {mod}", "importable"))
            except ImportError:
                lvl = "FAIL" if mod == "pytest" else "WARN"
                add((lvl, f"current {mod}", f"当前解释器缺 {mod}"))

    # submodule: 声明了 .agent-kb 但目录不存在/空 = 悬空指针
    gm = biz / ".gitmodules"
    if gm.exists() and ".agent-kb" in gm.read_text(encoding="utf-8", errors="replace"):
        sub = biz / ".agent-kb"
        if sub.is_dir() and any(sub.iterdir()):
            add(("PASS", "submodule .agent-kb", "已 checkout"))
        else:
            add(("WARN", "submodule .agent-kb", "悬空指针: git submodule update --init"))

    # index 漂移(生成物与正文一致性); kb_base = kb 载体目录(--repo 入参本身)
    repo_name = biz.resolve().name.lower()
    try:
        ok = check_indexes(kb_base, repo_name=repo_name)
        add(("PASS" if ok else "WARN", "index fresh",
             "up to date" if ok else f"stale: kb index --repo {kb_base} 重建"))
    except (FileNotFoundError, OSError):
        add(("FAIL", "index fresh", f"索引缺失: {kb_base / 'kb'} 不存在?"))

    # lint(仅 error 级算 FAIL; warning 常为存量豁免债)
    try:
        errs = lint_repo(kb_base, scope="agent-kb" if is_agent_kb_repo else "project")
        hard = [e for e in errs if not e.startswith("warning: ")]
        warns = len(errs) - len(hard)
        add((("FAIL" if hard else "PASS"), "kb lint",
             f"{len(hard)} errors" + (f", {warns} warnings" if warns else "")))
    except Exception as exc:  # noqa: BLE001 - doctor 永不因单项崩
        add(("WARN", "kb lint", f"lint 执行异常: {exc}"))

    # 已装 pre-push 门禁与母本一致性(A6)
    hook = biz / ".git" / "hooks" / "pre-push-gate.sh"
    master = root / "scripts" / "pre-push-gate.sh"
    if not hook.exists():
        add(("WARN", "pre-push gate", "未安装: powershell -File <agent-kb>/scripts/install-gate.ps1"))
    elif master.exists() and hook.read_text(encoding="utf-8", errors="replace").replace(
            "\r\n", "\n") != master.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n"):
        add(("WARN", "pre-push gate", "落后母本: 重跑 install-gate.ps1 刷新"))
    else:
        add(("PASS", "pre-push gate", "已装且与母本一致"))

    # .mcp.json 可解析且解释器标志路径存在
    mcp = biz / ".mcp.json"
    if mcp.exists():
        try:
            cfg = json.loads(mcp.read_text(encoding="utf-8"))
            cmd = next(iter(cfg["mcpServers"].values()))["command"]
            if Path(cmd).is_absolute():
                add(("WARN", ".mcp.json", f"绝对路径解释器(建议 kb init 重生成): {cmd}"))
            elif (biz / cmd).exists() or (biz / cmd.replace("\\", "/")).exists():
                add(("PASS", ".mcp.json", f"相对解释器可执行: {cmd}"))
            else:
                add(("FAIL", ".mcp.json",
                     f"相对解释器不可执行(venv 缺失或布局变化): {biz / cmd}"))
        except (json.JSONDecodeError, KeyError, StopIteration) as exc:
            add(("FAIL", ".mcp.json", f"解析失败: {exc}"))
    return checks


def render_doctor(checks: list[tuple[str, str, str]]) -> str:
    icon = {"PASS": "[ok]", "WARN": "[warn]", "FAIL": "[fail]"}
    width = max((len(n) for _, n, _ in checks), default=0)
    lines = [f"{icon[lvl]:<7}{n.ljust(width)}  {msg}" for lvl, n, msg in checks]
    n_fail = sum(1 for lvl, _, _ in checks if lvl == "FAIL")
    n_warn = sum(1 for lvl, _, _ in checks if lvl == "WARN")
    verdict = "all green" if not n_fail and not n_warn else f"{n_fail} fail / {n_warn} warn"
    return "\n".join(lines) + f"\n=> {verdict}"


def doctor_exit_code(checks: list[tuple[str, str, str]]) -> int:
    return 1 if any(lvl == "FAIL" for lvl, _, _ in checks) else 0
