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
