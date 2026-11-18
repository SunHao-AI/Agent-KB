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
              raw="107", corpus="7", biz_sha="9f8e7d6"):
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
                        lambda p, br: (int(corpus), f"origin/{br}"))


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
    地方 —— sync 本身是装配动作, 在这里说清楚; 检索侧不提(Task 3 的静默约定)。"""
    from kb import sync
    biz = _biz(tmp_path)
    for p in sorted((biz / ".agent-kb").rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    _stub_git(monkeypatch, biz)
    plan = sync.plan_sync(biz)
    assert plan.ok is False
    assert any("submodule update --init" in r for r in plan.reasons)


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
    commit = [c for c in calls if c[2] == "commit"][0]
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
    assert not [c for c in calls if c[2] == "commit"], calls


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
