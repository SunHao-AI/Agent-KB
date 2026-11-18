"""`kb sync` 及其只读提醒的测试。

惯例: 全仓 36 个测试文件无一跑真实 git, 本文件同样只 monkeypatch `_git_out` 与
`_run`, 断言的是**构造出的命令序列**。这样"永不 push""只 commit --only"这类红线
才有可执行的守护 —— 真实 git 测试既慢又会污染仓库, 且更难断言"没发生过什么"。

`_biz_root` 必须单独 patch: 它内部经 `_git_root` 直接起 `git rev-parse
--show-toplevel` 子进程(不走 `_git_out`, patch 不到), 而 tmp_path 是否落在某个
git 仓内取决于本机临时目录布局 —— 不 patch 就会把仓根解析到别处, 测试随机器漂移。
"""
from pathlib import Path


def _biz(tmp_path: Path) -> Path:
    biz = tmp_path / "biz"
    (biz / "docs" / "kb").mkdir(parents=True)
    (biz / ".agent-kb" / "kb").mkdir(parents=True)
    (biz / ".gitmodules").write_text(
        '[submodule ".agent-kb"]\n\tpath = .agent-kb\n\turl = https://x/agent.git\n'
        "\tbranch = master\n", encoding="utf-8")
    return biz


# ── lag_notice: 只读提醒 ────────────────────────────────────────────────────
def test_lag_notice_returns_one_line_with_freshness_caveat(tmp_path, monkeypatch):
    """提醒必须自带时效声明: 离线算的是上次 fetch 快照, 注定少报(setting 真实 7,
    离线只看到 1)。不写这句就给了"只差 1 个不着急"的虚假精确。"""
    from kb import bootstrap, sync
    biz = _biz(tmp_path)
    monkeypatch.setattr(sync, "_biz_root", lambda p: Path(p))

    def fake_git_out(args):
        if args[-1] == "origin/master":
            return "ccc"
        if any(a.startswith("HEAD..") for a in args):   # 带 pathspec 时末位是 "kb/"
            return "7"
        return None

    monkeypatch.setattr(bootstrap, "_git_out", fake_git_out)
    msg = sync.lag_notice(biz)
    assert msg is not None
    assert msg.startswith("[kb] 通用层落后 7 个语料提交"), msg
    assert "上次 fetch 快照" in msg and "kb sync" in msg


def test_lag_notice_none_when_zero_or_unknown(tmp_path, monkeypatch):
    """kb_lag==0 / 无从判定 → None。

    零漂移时打"指针最新"这类确认行是纯噪声: 本函数的存在前提是"响了就该动",
    没有行动项就不该有输出(kb-20261101-8321 里恒 WARN 被长期无视的教训)。
    """
    from kb import bootstrap, sync
    biz = _biz(tmp_path)
    monkeypatch.setattr(sync, "_biz_root", lambda p: Path(p))

    for ret in ("0", None):
        def fake_git_out(args, _r=ret):
            if args[-1] == "origin/master":
                return "ccc"
            if any(a.startswith("HEAD..") for a in args):
                return _r
            return None

        monkeypatch.setattr(bootstrap, "_git_out", fake_git_out)
        assert sync.lag_notice(biz) is None


def test_lag_notice_none_without_submodule(tmp_path, monkeypatch):
    """未 init submodule → 静默。环境装配问题归 kb doctor 的悬空指针项,
    两个面各管一件事, 检索侧不越界教人 init。"""
    from kb import bootstrap, sync
    biz = _biz(tmp_path)
    for p in sorted((biz / ".agent-kb").rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    monkeypatch.setattr(sync, "_biz_root", lambda p: Path(p))
    monkeypatch.setattr(bootstrap, "_git_out", lambda a: "ccc")
    assert sync.lag_notice(biz) is None


def test_lag_notice_silenced_by_env(tmp_path, monkeypatch):
    """KB_NO_LAG_HINT=1 关掉提醒(脚本化批量检索不被污染)。

    开关必须让**真的** lag_notice 跑起来: 若像 CLI 用例那样把 lag_notice 整个
    替换成常量桩, 开关读的是被替换掉的实现, 删掉实现里的 `if os.environ...`
    本用例仍恒绿 —— 恒绿测试比没测试更坏。故这里只打数据源 kb_corpus_lag。
    """
    from kb import sync
    biz = _biz(tmp_path)
    monkeypatch.setattr(sync, "_biz_root", lambda p: Path(p))
    monkeypatch.setattr(sync, "kb_corpus_lag",
                        lambda p, br: (7, f"origin/{br}"))
    assert sync.lag_notice(biz) is not None          # 前置: 无开关时确实会响
    monkeypatch.setenv("KB_NO_LAG_HINT", "1")
    assert sync.lag_notice(biz) is None


# ── plan_sync / apply_sync 共用桩 ───────────────────────────────────────────
def _stub_git(monkeypatch, biz, *, head="aaa", tip="bbb", dirty="",
              raw="107", corpus="7", biz_sha="9f8e7d6", biz_staged=""):
    """让 sync 模块内所有 git 探测返回可控值(不跑真实 git)。

    **四处必须正确，否则测试会假绿/假红：**
    ① 两个只读打桩点都要打。`sync._git_out` 只管 sync 自己发起的命令；`kb_corpus_lag`
       定义在 bootstrap、内部解析 `bootstrap._git_out`，只打前者完全管不到它。
       故 sync.py 在**模块顶层** import `kb_corpus_lag`，这里统一打桩。
    ② 按 `-C <路径>` 区分 submodule 与业务仓。两者的 `rev-parse HEAD` 末位都是
       `HEAD`，只判 `args[-1]` 会把业务仓 sha 当成 submodule 指针。
    ③ `rev-list` 要先于 `log` 判定：两者都含 `HEAD..<sha>` 区间参数。
    ④ `dirty` 必须经由 `_run` 桩返回 —— `plan_sync` 的 `status --porcelain` 走的是
       `_run`(写路径通道)而不是 `_git_out`，只打 ① 时 `dirty` 参数静默失效，
       "拒绝脏 submodule"用例会假红成"通过勘察"。
    """
    from kb import sync
    sub = str(biz / ".agent-kb")

    def fake_git_out(args):
        in_sub = args[:2] == ["-C", sub]
        if "rev-list" in args:
            return corpus if "kb/" in args else raw
        if "log" in args:
            return "abc1234 语料提交样例"
        if "status" in args and not in_sub:   # 业务仓 staged 计数探针(只读通道)
            return biz_staged
        if args[-1] == "FETCH_HEAD":           # fetch 之后的新 tip
            return tip
        if args[-1] == "HEAD":
            return head if in_sub else biz_sha
        if args[-1] == "origin/master":
            return tip
        return ""

    def fake_run(args):
        if "status --porcelain" in " ".join(args):
            return 0, dirty, ""
        return 0, "", ""

    monkeypatch.setattr(sync, "_biz_root", lambda p: Path(p))
    monkeypatch.setattr(sync, "_git_out", fake_git_out)
    monkeypatch.setattr(sync, "_run", fake_run)
    monkeypatch.setattr(sync, "kb_corpus_lag",
                        lambda p, br: (int(corpus) if corpus is not None else None,
                                       f"origin/{br}"))


def test_plan_refuses_repo_without_submodule(tmp_path, monkeypatch):
    """没有 .gitmodules 就绝不猜路径 —— 在陌生仓里"大概是 submodule 吧"会 checkout
    到错误目录。"""
    from kb import sync
    biz = tmp_path / "biz"
    (biz / "docs").mkdir(parents=True)
    _stub_git(monkeypatch, biz)
    plan = sync.plan_sync(biz)
    assert plan.declared is False and plan.ok is False
    assert "not-a-submodule-repo" in plan.reasons


def test_plan_refuses_dirty_submodule(tmp_path, monkeypatch):
    """submodule 有未提交改动就拒绝: checkout 会连带改动工作树, 把别人的 WIP
    卷进 bump 提交是必须堵死的事故(kb-20261116-0591 同源教训)。"""
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz, dirty=" M kb/pitfall/backend/x.md\n?? kb/new.md\n")
    plan = sync.plan_sync(biz)
    assert plan.ok is False
    assert any(r == "dirty-submodule" for r in plan.reasons)
    assert "kb/pitfall/backend/x.md" in plan.dirty


def test_plan_reports_uninitialized_submodule_for_init(tmp_path, monkeypatch):
    """.agent-kb 目录空 = 未 init。这是**唯一**该指回 submodule update --init 的
    地方 —— sync 本身是装配动作, 在这里说清楚; 检索侧不提(Task 3 的静默约定)。
    拒绝码必须是独立稳定码 submodule-not-initialized(§4.4), 不得与其他前置
    拒绝共用泛化码; apply 层同样必须带这个码(码在 plan 生产、apply 透传,
    任何一侧回退成 "precondition" 都会红)。"""
    from kb import sync
    biz = _biz(tmp_path)
    for p in sorted((biz / ".agent-kb").rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    _stub_git(monkeypatch, biz)
    plan = sync.plan_sync(biz)
    assert plan.ok is False
    assert plan.code == "submodule-not-initialized", plan.code
    assert any("submodule update --init" in r for r in plan.reasons)
    res = sync.apply_sync(biz)
    assert res.ok is False and res.exit_code == 1
    assert res.code == "submodule-not-initialized", res.code
    assert "precondition" not in res.code
    assert "submodule update --init" in res.detail, res.detail


def _recorder(monkeypatch):
    """记录全部 git **写**命令, 供"永不 push""只 commit --only"这类红线断言。

    必须在 `_stub_git` **之后**调用, 且链式委托原桩: `_stub_git` 已经接管 `_run`
    以提供 `status --porcelain` 的脏输出(见其 docstring ④), 直接覆盖会让 dirty
    失效。这里保留其返回值, 只加一层记录。

    注意 `plan_sync` 的 `status --porcelain` 也在记录内, 所以列表不为空;
    断言一律针对"有没有 fetch/checkout/commit/push", 而不是"有没有调用"。
    """
    from kb import sync
    inner = sync._run
    calls: list[list[str]] = []

    def record(args):
        calls.append(list(args))
        return inner(args)

    monkeypatch.setattr(sync, "_run", record)
    return calls


def _verbs(calls):
    """取每条命令的 git 子命令名(args 形如 ["-C", 路径, 子命令, ...])。"""
    return [c[2] for c in calls if len(c) > 2]


def test_plan_counts_biz_staged_and_renders_notice(tmp_path, monkeypatch):
    """spec §4.3: 业务仓有已 staged 文件时勘察须提示"不涉及它们"(纯提示, 非拒绝)。

    X 列计数守护: 首列 M/空格的未 staged 改动不得混进计数(否则提示数字说谎);
    走只读 _git_out ⇒ 写命令记录恒零 status 条目(读探测不污染写路径守护)。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz,
              biz_staged="M  .agent-kb\nM  other.py\n MM wip.py\n?? untracked\n")
    calls = _recorder(monkeypatch)
    plan = sync.plan_sync(biz)
    assert plan.ok and plan.staged == 2, plan.staged
    out = sync.render_plan(plan)
    assert "已 staged 文件" in out and "commit --only" in out, out
    assert _verbs(calls) == ["status"], _verbs(calls)   # 仅 submodule 脏检查;
    # 业务仓 staged 探针走只读 _git_out, 不得以业务仓为 -C 目标出现在写记录里
    assert not any(len(c) > 1 and c[1] == str(biz) for c in calls), calls


def test_plan_renders_lag_unknown_without_lying_zero(tmp_path, monkeypatch):
    """语料探针失败(rev-list 出 None)时勘察不得渲染"落后 0"/"无需同步"。

    None≠0 纪律的勘察面: apply 里 corpus-lag-unknown 守的是写路径, 但勘察打印
    "语料落后 0 → 无需同步"同样会把人支开(fetch 恰是恢复探针的自愈步骤,
    所以也不进 reasons 不判失败 —— §4.4 该码的原义是"fetch 后仍无法计算")。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz, corpus=None)
    plan = sync.plan_sync(biz)
    assert plan.lag is None and plan.ok          # 不拒绝: fetch 能自愈
    out = sync.render_plan(plan)
    assert "无从判定" in out and "落后 0" not in out, out


def test_apply_short_circuits_when_corpus_fresh(tmp_path, monkeypatch):
    """fetch 后语料口径为 0 → 不 checkout 不 commit。原始数很大也不算落后
    (漂移全在 src/kb/ 与 traces/)。

    fetch 必然先于 lag 判定: 不 fetch 就只有上次快照, 看不到真实漂移。故这里
    允许 status + fetch, 守的是"没有工作树改动、没有提交"。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz, corpus="0", raw="99")
    calls = _recorder(monkeypatch)
    res = sync.apply_sync(biz)
    assert res.ok and res.exit_code == 0
    assert "语料已最新" in res.detail and "99" in res.detail
    assert _verbs(calls) == ["status", "fetch"], _verbs(calls)   # 无 checkout / 无 commit


def test_apply_refuses_when_corpus_lag_unknown(tmp_path, monkeypatch):
    """fetch 后语料探针本身失败(返回 None)→ corpus-lag-unknown, 绝不判"已最新"。

    None 与 0 语义完全不同: 0 是"算过, 不差", None 是"没算出来"(损坏对象、与每日
    traces 定时任务抢 `.git/index.lock` 等, §4.4 明写的场景)。旧实现
    `kb_corpus_lag(...)[0] or 0` 把两者压成同一个 0 → 探针一抖动就 up-to-date +
    exit 0, 这正是本模块要消灭的虚假成功(与 kb-20261101-8321 同一类病)。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz, corpus="7")
    calls = _recorder(monkeypatch)
    monkeypatch.setattr(sync, "kb_corpus_lag",
                        lambda p, br: (None, "rev-list 失败"))
    res = sync.apply_sync(biz)
    assert res.ok is False, res
    assert res.code == "corpus-lag-unknown", res.code
    assert res.exit_code == 1, res.exit_code            # §4.4: 校验类失败退 1
    assert "未产生任何写入" in res.detail, res.detail
    assert res.commit_sha is None
    assert _verbs(calls) == ["status", "fetch"], _verbs(calls)   # 无 checkout / 无 commit


def test_apply_raw_count_comes_from_post_fetch_tip(tmp_path, monkeypatch):
    """"语料已最新(原始 N 个提交)"的 N 必须是 **fetch 后** 的口径。

    raw_lag 在勘察时(fetch 前)算, 文案却在 fetch 后用: fetch 捞出 50 个提交后仍打
    "原始 3 个"是在给人看旧地图。桩把两个 tip 分开给(勘察 `bbb` / fetch 后 `ccc`),
    按区间参数区分两次查询, 这样"取错了哪一次"在断言里可分辨。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz, corpus="0")
    calls = _recorder(monkeypatch)
    inner = sync._git_out
    raw_by_range = {"HEAD..bbb": "3", "HEAD..ccc": "50"}

    def fake(args):
        if "rev-list" in args:
            if "kb/" in args:
                return "0"                       # 语料口径: 前后都是 0
            return raw_by_range[next(a for a in args if a.startswith("HEAD.."))]
        if args[-1] == "origin/master":
            return "bbb"                         # 勘察时点: 上次 fetch 的旧 tip
        if args[-1] == "FETCH_HEAD":
            return "ccc"                         # 本次 fetch 到的新 tip
        return inner(args)

    monkeypatch.setattr(sync, "_git_out", fake)
    res = sync.apply_sync(biz)
    assert res.ok and res.exit_code == 0
    assert "原始 50" in res.detail, res.detail     # fetch 后口径
    assert "原始 3" not in res.detail, res.detail  # 不得复用 fetch 前旧数
    assert _verbs(calls) == ["status", "fetch"], _verbs(calls)


def test_apply_maps_fetch_timeout_to_fetch_failed(tmp_path, monkeypatch):
    """git fetch 挂死(>120s, 本模块唯一网络调用)→ 走 fetch-failed, 不是裸 traceback。

    `_run` 原本没有 `_git_out` 那层 `TimeoutExpired` 捕获, 超时直接穿透到 CLI 顶层
    崩栈: 人看到的是 Python 栈, 不是"fetch 失败, 未产生任何写入"。

    这条用例**必须跑真实 `_run`**(超时捕获点在它内部): `_stub_git` 把 `_run` 整个
    换掉了, 故这里先存原始函数再挂回去, 只在最底层 `subprocess.run` 上打桩。
    """
    import subprocess
    from types import SimpleNamespace

    from kb import sync
    real_run = sync._run                        # 必须在 _stub_git 之前取
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    monkeypatch.setattr(sync, "_run", real_run)  # 恢复真实 _run
    calls = _recorder(monkeypatch)
    spawned: list[list[str]] = []

    def fake_spawn(argv, **kwargs):
        spawned.append(list(argv))
        assert kwargs.get("timeout"), "写路径必须带超时, 否则挂死无上限"
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(argv, 120)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_spawn)
    res = sync.apply_sync(biz)
    assert res.ok is False, res
    assert res.code == "fetch-failed", res.code
    assert res.exit_code == 1
    assert "未产生任何写入" in res.detail and "超时" in res.detail, res.detail
    assert any("fetch" in a for a in spawned), spawned   # 桩确实被走到(防假绿)
    assert _verbs(calls) == ["status", "fetch"], _verbs(calls)


def test_apply_reports_fetch_failure_without_any_write(tmp_path, monkeypatch):
    """fetch 非零退出(断网/鉴权失败)→ fetch-failed + git stderr 原样透传, 零写入。

    apply 层的拒绝码此前只在 plan 层有用例, 这一条把"网络失败不动工作树"钉成可执行
    契约: 若有人把 fetch 挪到 checkout 之后, 本用例必红。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    calls = _recorder(monkeypatch)
    inner = sync._run

    def failing_fetch(args):
        out = inner(args)
        if args[2] == "fetch":
            return 128, "", "fatal: unable to access 'https://x/agent.git/': timed out"
        return out

    monkeypatch.setattr(sync, "_run", failing_fetch)
    res = sync.apply_sync(biz)
    assert res.ok is False and res.exit_code == 1
    assert res.code == "fetch-failed", res.code
    assert res.commit_sha is None
    assert "未产生任何写入" in res.detail, res.detail
    assert "unable to access" in res.detail            # git stderr 原样给出
    assert _verbs(calls) == ["status", "fetch"], _verbs(calls)   # 无 checkout / 无 commit


def test_apply_reports_commit_failure_but_keeps_checkout(tmp_path, monkeypatch):
    """commit 失败(hook 拒/身份缺失)→ commit-failed; checkout **不回滚**。

    不回滚是幂等性裁定: submodule 已在新 tip, 重跑一次只会补提交, 不必把指针撤回
    去再走一遍 checkout; 且 commit_sha 必须是 None —— 谎报 sha 会让脚本消费方以为
    提交成功了。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    calls = _recorder(monkeypatch)
    inner = sync._run

    def failing_commit(args):
        out = inner(args)
        if args[2] == "commit":
            return 1, "", "pre-push gate 前置检查未通过"
        return out

    monkeypatch.setattr(sync, "_run", failing_commit)
    monkeypatch.setattr(sync, "_indexes_fresh", lambda *a, **k: True)
    res = sync.apply_sync(biz)
    assert res.ok is False and res.exit_code == 1
    assert res.code == "commit-failed", res.code
    assert res.commit_sha is None, res.commit_sha     # 没有提交就没有 sha
    assert "重跑幂等" in res.detail and "pre-push gate" in res.detail, res.detail
    checkout = [c for c in calls if c[2] == "checkout"]
    assert len(checkout) == 1 and checkout[0][-1] == "bbb", checkout   # 留在新 tip, 不回滚


def test_apply_commits_only_the_gitlink(tmp_path, monkeypatch):
    """业务仓提交必须走 `commit --only .agent-kb`。

    实测: staged a+b+wip 时 `commit --only a` 之后索引仍留 b/wip, 提交只含 a ——
    这正是"不把他人 WIP 卷进 bump"的安全前提。若有人改成 `git add -A` + `commit`,
    本用例必红。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    calls = _recorder(monkeypatch)
    monkeypatch.setattr(sync, "_indexes_fresh", lambda *a, **k: True)
    res = sync.apply_sync(biz)
    assert res.ok and res.commit_sha == "9f8e7d6", res       # 业务仓 HEAD 由桩给出
    assert _verbs(calls) == ["status", "fetch", "checkout", "commit"], _verbs(calls)
    commit = next(c for c in calls if c[2] == "commit")
    assert "--only" in commit and ".agent-kb" in commit, commit
    assert "add" not in _verbs(calls), _verbs(calls)         # 绝不 git add


def test_apply_never_pushes(tmp_path, monkeypatch):
    """永不 push —— 业务仓与 submodule 都不推(设计红线)。

    两条 git 通道都要拦: `_run`(写命令)与 `_git_out`(plan_sync 的只读探测也
    拼 git 命令)。apply_sync 的全部构造路径都跑一遍: 本用例走通 status→fetch→
    checkout→commit 全链, 回滚支路的第二次 checkout 由
    test_apply_rolls_back_when_tip_index_stale 覆盖 —— 两条合起来穷尽模块内
    全部 git 命令, 任何一条含 push/--force 都会落进这里。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    calls = _recorder(monkeypatch)
    inner_out = sync._git_out
    read_calls: list[list[str]] = []

    def record_out(args):
        read_calls.append(list(args))
        return inner_out(args)

    monkeypatch.setattr(sync, "_git_out", record_out)
    monkeypatch.setattr(sync, "_indexes_fresh", lambda *a, **k: True)
    sync.apply_sync(biz)
    assert read_calls, "plan_sync 的只读探测应被记录"   # 防桩失效致假绿
    for c in calls + read_calls:
        assert "push" not in c, c
        assert "--force" not in c, c


def test_apply_rolls_back_when_tip_index_stale(tmp_path, monkeypatch):
    """tip 自带索引与正文不一致 → 回滚 checkout 且不提交。

    这一步是 kb-20261101-8321 的结构性收口: 指针永远不指向自带过期索引的 tip,
    `sections` 检索面整层缺失就不会再复发。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    calls = _recorder(monkeypatch)
    monkeypatch.setattr(sync, "_indexes_fresh", lambda *a, **k: False)
    res = sync.apply_sync(biz)
    assert res.ok is False and res.code == "tip-index-stale"
    assert res.exit_code == 1
    checkout = [c for c in calls if c[2] == "checkout"]
    assert len(checkout) == 2, checkout                      # 去 + 回滚
    assert checkout[1][-1] == "aaa", checkout[1]             # 回到原指针
    assert "已回滚到 aaa" in res.detail, res.detail           # 回滚成功才允许这么声称
    assert not [c for c in calls if c[2] == "commit"], calls


def test_apply_reports_when_rollback_checkout_fails(tmp_path, monkeypatch):
    """回滚 checkout 自身失败(git lockfile 与每日 traces 定时任务竞争等) →
    detail 必须如实报"回滚失败"并给出人工命令(§4.3 错误教义: 如实报错并停下)。

    旧实现在这里无条件声称"已回滚到 <head>": 回滚失败时 submodule 实际仍停在被拒
    tip, 消息对仓库状态撒谎。本用例把第二次的回滚 checkout 打桩成非零退出, 断言
    失败措辞 + 人工命令 + tip-index-stale 码仍在; "已回滚到"的旧断言随之变红。
    """
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    calls = _recorder(monkeypatch)
    inner = sync._run

    def failing_rollback(args):
        out = inner(args)                                  # 先经 recorder 记录
        # 只让回滚那次(回原指针 aaa)失败, 正向 checkout 到 tip 照常成功
        if args[2] == "checkout" and args[-1] == "aaa":
            return 128, "", "fatal: Unable to create '.git/index.lock': File exists"
        return out

    monkeypatch.setattr(sync, "_run", failing_rollback)
    monkeypatch.setattr(sync, "_indexes_fresh", lambda *a, **k: False)
    res = sync.apply_sync(biz)
    assert res.ok is False and res.code == "tip-index-stale"   # 码不因回滚态而丢
    assert res.exit_code == 1
    rollback = [c for c in calls if c[2] == "checkout" and c[-1] == "aaa"]
    assert rollback, calls                                     # 回滚确实尝试过
    assert "回滚 checkout 失败" in res.detail, res.detail
    assert "git -C .agent-kb checkout --detach aaa" in res.detail, res.detail
    assert "Unable to create" in res.detail                    # git stderr 原样透传
    assert "已回滚到" not in res.detail, res.detail             # 不得谎称已回滚
    assert not [c for c in calls if c[2] == "commit"], calls


def _stub_missing_origin_ref(monkeypatch, biz):
    """把 origin/<branch> 的 rev-parse --verify 打成空(本机从未 fetch 过)。"""
    from kb import sync
    inner = sync._git_out

    def fake(args):
        if args[-1] == "origin/master":
            return ""
        return inner(args)

    monkeypatch.setattr(sync, "_git_out", fake)


def test_apply_refuses_missing_origin_ref_with_its_own_code(tmp_path,
                                                           monkeypatch):
    """从未 fetch 过 → origin/<branch> 不存在: 独立码 origin-ref-missing,
    detail 指回 fetch。与未 init 分码是 §4.4 的要求(两个场景机器面必须可分辨),
    任何"把多个拒绝压成一个泛化码"的改法都会被这两条用例各红一次。"""
    from kb import sync
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz)
    _stub_missing_origin_ref(monkeypatch, biz)
    res = sync.apply_sync(biz)
    assert res.ok is False and res.exit_code == 1
    assert res.code == "origin-ref-missing", res.code
    assert "需先 fetch" in res.detail, res.detail
    assert "submodule update --init" not in res.detail   # init 指引只属未 init 场景


def test_cli_sync_plan_reject_exits_1(tmp_path, monkeypatch, capsys):
    """CLI plan 模式拒绝态必须退 1。`plan.declared` 在 dirty-submodule 拒绝下
    同样为真, 若 CLI 写成 `0 if plan.ok or plan.declared` 会把失败报成成功,
    脚本消费方(kb sync && ...)据此以为已同步。"""
    from kb.cli import _dispatch
    biz = _biz(tmp_path)
    _stub_git(monkeypatch, biz, dirty=" M kb/pitfall/backend/x.md\n")
    # _biz_root 已被 _stub_git 打成恒等: 直接喂业务仓根即可
    rc = _dispatch(["sync", "--repo", str(biz)])
    assert rc == 1, rc
    out = capsys.readouterr().out
    assert "dirty-submodule" in out
