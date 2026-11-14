"""I-9: pre-push 门禁增量 base 锚点测试（母本 resolve_base + PREPUSH_GATE_PROBE）。

背景（roadmap I-9，2026-11-04 拍板修复）：母本 `scripts/pre-push-gate.sh` 的四段
增量判定（lint / mypy 棘轮 / kb / 前端）此前各自抄写"新分支首推锚 origin/master"，
仓内没有 origin/master 时（web 仓只有 origin/main 与 origin/develop）merge-base 失败
→ base=local_sha → diff 为空 → 四段静默整体跳过 = 新分支首推零门禁。

本文件用 Git 自带的 POSIX sh 直接跑母本的 `PREPUSH_GATE_PROBE=base` 诊断出口，
在真实 git 仓上断言四种场景的锚点与 base：
  1. 只有 origin/main（无 master/HEAD）→ 锚 main，base=merge-base（旧行为是 local_sha）
  2. 有 origin/HEAD → 优先 HEAD
  3. 常规推送（remote_sha 非 0）→ 行为与修复前一致
  4. 无任何 origin/* → base 退化为空树（偏严）且打 WARN
  5. D-71: remote_sha 在本地不可达（force-push 后 gc / 浅克隆）→ 不得退回该
     sha（下游 diff 全 rc!=0 被静默吞 = 五面失明），改走锚点/空树 + WARN
  6. D-71 对照：旧 tip 可达但无共同祖先（孤儿分支覆盖推）→ 仍退回旧 tip（偏严可用）

sh.exe 或 git 缺失时整模块 skip（CI 与非 Windows 环境不假失败）。
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "scripts" / "pre-push-gate.sh"

# 本文件会被 pre-push 门禁自己跑起来: git 在 hook 进程里 export 了 GIT_DIR /
# GIT_WORK_TREE 等变量(实测门禁内 4 个用例全红, 直接跑全绿), 子进程若不清理这些
# 变量, 临时仓里的 `git init/commit/push` 会被拽回到宿主仓, 建仓失败或污染宿主索引。
_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
            "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES")


def _clean_env(path_prefix: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV}
    if path_prefix:
        env["PATH"] = os.pathsep.join([path_prefix, env.get("PATH", "")])
    return env


def _sh() -> str:
    git = shutil.which("git")
    if not git:
        pytest.skip("git 不可用")
    # Git for Windows: <root>\cmd\git.exe → <root>\usr\bin\sh.exe
    cand = Path(git).resolve().parent.parent / "usr" / "bin" / "sh.exe"
    if not cand.exists():
        cand2 = shutil.which("sh")
        if not cand2:
            pytest.skip("未找到 Git 自带 sh.exe")
        return cand2
    return str(cand)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True, text=True, check=True, env=_clean_env(),
    )
    return out.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _probe(repo: Path, ref_lines: str) -> tuple[str, str, int]:
    """跑母本探针: 返回 (stdout, stderr, rc)。不碰 venv/npm(探针在仓型探测前退出)。

    PATH 必须补 sh.exe 同级的 usr/bin: 真实 hook 由 git 注入该路径, 直接调 sh.exe
    时不补会让脚本里的 `mkdir` 等 coreutils 全部 command not found(实测: 首个
    mkdir 静默失败 → 误入陈旧锁分支 → 接管失败 exit 1, 与门禁逻辑无关的假失败)。
    """
    sh = _sh()
    env = _clean_env(os.path.dirname(sh))
    env["PREPUSH_GATE_PROBE"] = "base"
    r = subprocess.run(
        [sh, str(GATE)], input=ref_lines, capture_output=True, text=True,
        # 母本脚本的中文 WARN 是 UTF-8 字节: 不写 encoding 时 text=True 按控制台码页
        # 解码, 中文 Windows(GBK)下 _readerthread 抛 UnicodeDecodeError → r.stderr=None
        # → 下面 "xxx" in err 报成 TypeError 而非真断言(2026-11-14 门禁实跑拦下两条)。
        encoding="utf-8", errors="replace",
        cwd=str(repo), env=env,
    )
    return r.stdout, r.stderr, r.returncode


@pytest.fixture()
def repo(tmp_path: Path) -> dict:
    """bare origin + 工作仓: main 上 1 个提交, feature 从其分出再加 1 个提交。"""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main", "-q")
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main", "-q")
    _commit(work, "base.txt")
    main_sha = _git(work, "rev-parse", "HEAD")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main")
    _git(work, "fetch", "-q", "origin")
    _git(work, "checkout", "-q", "-b", "feature")
    _commit(work, "feat.txt")
    return {"dir": work, "main": main_sha, "feat": _git(work, "rev-parse", "HEAD")}


def _ref_line(repo, branch: str, remote_sha: str) -> str:
    d = repo["dir"] if isinstance(repo, dict) else repo
    local = _git(d, "rev-parse", branch)
    return f"refs/heads/{branch} {local} refs/heads/{branch} {remote_sha}\n"


ZERO = "0" * 40


def test_new_branch_anchors_origin_main_when_no_master(repo: dict):
    """I-9 核心回归：仓内只有 origin/main 时, 新分支首推必须锚到 main。

    修复前: base == local_sha（diff 空 → 四段静默跳过）；
    修复后: base == merge-base(feature, origin/main) == main 的 tip。
    """
    out, _, rc = _probe(repo["dir"], _ref_line(repo, "feature", ZERO))
    assert rc == 0
    assert "anchor=refs/remotes/origin/main" in out, out
    assert f"base={repo['main']}" in out, out
    assert f"base={repo['feat']}" not in out, "base 退化成本地 tip = I-9 未修好"


def test_origin_head_takes_precedence_over_hardcoded_names(repo: dict):
    """origin/HEAD 优先于 main/master 的固定顺序。

    构造: origin 上同时有 main 与 master, 且 HEAD 指向 **master** —— 若不读 HEAD
    会按固定顺序锚到 main, 读了 HEAD 才锚 master。anchor 显示的是 symbolic-ref
    解引用后的目标 ref 名(实现如此), 故断言 master 而非字面 HEAD。
    """
    work = repo["dir"]
    _git(work, "checkout", "-q", "-b", "master", repo["main"])
    _commit(work, "on-master.txt")
    _git(work, "push", "-q", "origin", "master")
    _git(work, "fetch", "-q", "origin")
    _git(work, "remote", "set-head", "origin", "master")
    _git(work, "checkout", "-q", "feature")
    out, _, _ = _probe(work, _ref_line(repo, "feature", ZERO))
    assert "anchor=refs/remotes/origin/master" in out, out


def test_regular_push_unchanged(repo: dict):
    """常规推送（remote_sha 非 0）：base 仍是 merge-base(远端旧 tip, 本地 tip)。"""
    out, _, _ = _probe(repo["dir"], _ref_line(repo, "main", repo["main"]))
    assert f"base={repo['main']}" in out, out


def test_no_remote_falls_back_to_empty_tree_with_warn(tmp_path: Path):
    """无 origin/*：base 退化为空树（全树当增量, 偏严）并打 WARN, 绝不静默放行。"""
    lone = tmp_path / "lone"
    lone.mkdir()
    _git(lone, "init", "-b", "main", "-q")
    head = _commit(lone, "a.txt")
    out, err, rc = _probe(lone, _ref_line(lone, "main", ZERO))
    empty_tree = subprocess.run(
        ["git", "-C", str(lone), "hash-object", "-t", "tree", "/dev/null"],
        capture_output=True, text=True, check=True, env=_clean_env()).stdout.strip()
    assert rc == 0
    assert f"base={empty_tree}" in out, out
    assert f"base={head}" not in out
    assert "anchor=<none>" in out, out
    assert "退化为全树" in err, err


def _orphan_ref(tmp_path: Path, origin: Path, name: str, force: bool = False) -> str:
    """往 origin 塞一个与 main 无共同祖先的孤儿分支并返回其 sha（模拟覆盖推历史）。"""
    orph = tmp_path / "orphan"
    orph.mkdir()
    _git(orph, "init", "-b", "orphan", "-q")
    sha = _commit(orph, "orphan.txt")
    args = ["push", "-q", str(origin), f"orphan:{name}"]
    if force:
        args.insert(1, "--force")
    _git(orph, *args)
    return sha


def test_force_push_unreachable_remote_sha_not_used_as_base(repo: dict, tmp_path: Path):
    """D-71 回归：remote_sha 本地不可达时，base 绝不能退回该 sha。

    场景复刻(2026-11-14 探针实测): 远端 main 被孤儿历史覆盖推，而本地从未 fetch
    过该历史(新克隆/浅克隆/未同步视角一致——git 给 hook 的 remote_sha 来自推送时
    的远端通告，**不保证**本地对象库有该对象)。修复前 resolve_base 的 merge-base
    兜底 `|| rb_b=$rb_remote` 直接吐出不可达 sha → 下游每条 `git diff base..tip`
    rc!=0 且零输出，被 `|| continue` / 空判定静默吞掉 → 增量 lint、mypy、kb、
    前端、全量 pytest **五面全部失明**(假绿放行)。
    修复后: cat-file 验可达，不可达则落锚点链——本 fixture 有 origin/main，
    base 应为 merge-base(feature, origin/main)=main tip；并打 WARN 可见退化。
    """
    work, origin = repo["dir"], tmp_path / "origin.git"
    orphan_sha = _orphan_ref(tmp_path, origin, "main", force=True)
    # 刻意不 fetch: 复刻"远端 sha 在本地不可达"的对象库状态
    r = subprocess.run(
        ["git", "-C", str(work), "cat-file", "-e", f"{orphan_sha}^{{commit}}"],
        capture_output=True, env=_clean_env())
    assert r.returncode != 0, "前置条件不成立: 旧 tip 应不可达"

    local = _git(work, "rev-parse", "feature")
    out, err, rc = _probe(work, (
        f"refs/heads/feature {local} refs/heads/main {orphan_sha}\n"))
    assert rc == 0
    assert f"base={orphan_sha}" not in out, "base 退回不可达 sha = D-71 未修好"
    assert f"base={repo['main']}" in out, out
    assert "本地不可达" in err, err
    assert f"base={local}" not in out, "base 退化成本地 tip = diff 必空, 失明未除"
    # 失明已除: 修复后的 base 让母本收集段的 diff 正常执行(rc=0 而非 bad object)
    d = subprocess.run(
        ["git", "-C", str(work), "diff", "--name-only", repo["main"], local, "--", "*.py"],
        capture_output=True, text=True, env=_clean_env())
    assert d.returncode == 0, d.stderr


def test_force_push_reachable_orphan_tip_still_used_as_base(repo: dict, tmp_path: Path):
    """D-71 对照组：旧 tip 本地可达但无共同祖先 → base 仍退回旧 tip（偏严可用）。

    这是 resolve_base 兜底 `|| rb_b=$rb_remote` 的**合法用途**（孤儿分支覆盖推，
    旧 tip 还在本地对象库）——修复加 cat-file 验可达时不能把这个分支打断：
    若把它一并落空树，diff 范围同样正确但多扫全历史 blob，且与注释语义不符。
    """
    work, origin = repo["dir"], tmp_path / "origin.git"
    orphan_sha = _orphan_ref(tmp_path, origin, "side")   # 可达的孤儿分支 tip
    _git(work, "fetch", "-q", "origin")
    local = _git(work, "rev-parse", "feature")
    out, err, rc = _probe(work, (
        f"refs/heads/feature {local} refs/heads/side {orphan_sha}\n"))
    assert rc == 0
    assert f"base={orphan_sha}" in out, out
    assert "本地不可达" not in err, err
