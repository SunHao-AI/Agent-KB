from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from kb import trace as kbtrace
from kb.gate import DuplicateCandidate, GateViolation, create_draft, export_entry
from kb.gate import review as gate_review
from kb.gate import set_scope as gate_set_scope
from kb.entry import dump_entry, parse_entry
from kb.index import build_indexes, check_indexes
from kb.layers import get_layered, related_layers, search_layers_report
from kb.lint import lint_repo
from kb.new_entry import create_entry
from kb.promote import promote
from kb.query import due_review, get_entry, needs_scope, related, stat


def _dispatch(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kb")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="repo root containing kb/")
    common.add_argument("--agent-kb", action="append", default=[],
                        help="额外检索层(可重复), 如 .agent-kb")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", parents=[common])
    p_new.add_argument("type")
    p_new.add_argument("--domain", required=True)
    p_new.add_argument("--scope", default="project",
                       choices=["project", "stack", "universal"])
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--generated", action="store_true")
    p_new.add_argument("--body-file", default=None)
    # pitfall/rca 需要 severity(模板默认 medium); 对齐 MCP kb_create, 显式覆盖用本参数
    p_new.add_argument("--severity", default=None,
                       choices=["low", "medium", "high", "critical"])

    p_lint = sub.add_parser("lint", parents=[common])
    # choices 严格校验, 拼错立即 exit 2 而非静默关闭落位检查
    p_lint.add_argument("--scope", default="project", choices=["project", "agent-kb"])
    p_lint.add_argument("--strict", action="store_true",
                        help="warning 视为硬错误; 配合 baseline 只挡增量")
    p_lint.add_argument("--baseline", default=None,
                        help="存量 warning 豁免清单文件, 缺省 <repo>/.kb-lint-baseline")
    p_lint.add_argument("--update-baseline", action="store_true",
                        help="把当前全部 warning 固化进 baseline 文件后通过")
    p_idx = sub.add_parser("index", parents=[common])
    p_idx.add_argument("--check", action="store_true")
    p_idx.add_argument("--repo-name", default=None,
                       help="repo 名(写入索引 repo 字段), 默认取 --repo 目录名")

    p_s = sub.add_parser("search", parents=[common])
    for flag in ("type", "domain", "tag", "scope", "status", "confidence", "query"):
        p_s.add_argument(f"--{flag}", default=None)
    p_s.add_argument("--limit", type=int, default=20)
    g = p_s.add_mutually_exclusive_group()
    g.add_argument("--trace", dest="trace_on", action="store_true", default=None,
                   help="本次强制记录检索 trace")
    g.add_argument("--no-trace", dest="trace_on", action="store_false",
                   help="本次强制不记录检索 trace")

    p_show = sub.add_parser("show", parents=[common]); p_show.add_argument("id")
    p_rel = sub.add_parser("related", parents=[common]); p_rel.add_argument("id")
    p_stat = sub.add_parser("stat", parents=[common])
    p_stat.add_argument("--due-review", action="store_true")
    p_stat.add_argument("--needs-scope", action="store_true")
    p_stat.add_argument("--format", default="json", choices=["json", "md"])
    p_pro = sub.add_parser("promote", parents=[common]); p_pro.add_argument("id"); p_pro.add_argument("--to", required=True)

    p_rev = sub.add_parser("review", parents=[common])
    p_rev.add_argument("id"); p_rev.add_argument("--to", required=True,
        choices=["draft", "proposed", "accepted", "deprecated", "superseded"])
    p_rev.add_argument("--evidence", default=None,
                       help="实测证据(仅 --to accepted 生效): 写入 verification.evidence 留痕")
    p_rev.add_argument("--confidence", default=None,
                       choices=["verified", "probable", "speculative"],
                       help="提升 confidence(仅 --to accepted 生效); accepted 前须非 speculative")
    p_rev.add_argument("--as-agent", action="store_true",
                       help="agent 自审语义: accepted 写 verified_by=agent + auto-reviewed "
                            "标签(与 MCP kb_review 对齐), 供事后抽查回滚")
    p_ss = sub.add_parser("set-scope", parents=[common])
    p_ss.add_argument("id"); p_ss.add_argument("scope", choices=["project", "stack", "universal"])
    p_ex = sub.add_parser("export", parents=[common])
    p_ex.add_argument("id"); p_ex.add_argument("--to-repo", required=True)
    p_ex.add_argument("--to-scope", required=True, choices=["stack", "universal"])

    p_init = sub.add_parser("init", parents=[common])
    p_init.add_argument("--kb-dir", default="docs", help="仓内知识库目录(生成物含 kb/)")
    p_init.add_argument("--repo-name", default=None, help="写入 --repo-name 的名字, 默认仓目录名小写")
    p_init.add_argument("--mcp-name", default="kb", help=".mcp.json 中 server 键名")
    p_init.add_argument("--force", action="store_true", help="覆盖已存在的 .mcp.json")
    p_init.add_argument("--serve-url", default=None,
                        help="团队观测服务端地址(FR-2.5): 地址进 .mcp.json, 凭据进 ~/.kb/config.toml")
    p_init.add_argument("--token", default=None, help="与 --serve-url 联用的访问令牌")

    p_doc = sub.add_parser("doctor", parents=[common])
    p_doc.add_argument("--current-python", action="store_true",
                       help="追加检查当前解释器(kb CLI 自身运行环境)")

    # 观测面(FR-2): serve=服务端(读侧, 只读); web=瘦客户端启动器(自动代拉起)
    p_serve = sub.add_parser("serve", help="观测服务端(只读 REST+SSE, 默认仅本机)")
    p_serve.add_argument("--repo", default=None,
                         help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_serve.add_argument("--port", type=int, default=4320)
    p_serve.add_argument("--bind", default="127.0.0.1",
                         help="非本机绑定必须带 --token(红线)")
    p_serve.add_argument("--token", default=None)
    p_serve.add_argument("--default-caller", default=None,
                         help="单项目视图默认项目名(小写目录名)")
    p_serve.add_argument("--install-autostart", action="store_true",
                         help="注册系统服务常驻(Windows 计划任务/systemd 用户 unit, 幂等)")
    p_serve.add_argument("--uninstall-autostart", action="store_true",
                         help="撤销 --install-autostart 注册的系统服务")
    p_web = sub.add_parser("web", help="打开观测面板(无 serve 时代拉起)")
    p_web.add_argument("--repo", default=None,
                       help="Agent-KB 仓根, 默认为本仓 kb_root()")
    p_web.add_argument("--port", type=int, default=4320)
    p_web.add_argument("--caller", default="",
                       help="项目身份; 缺省按当前目录名推断")
    p_web.add_argument("--all", action="store_true", help="直接进多项目联邦视图")
    p_web.add_argument("--no-browser", action="store_true", help="只打印 URL")

    # FR-2.4: trace → prompt-spider-ui 实时直播(驱动克隆仓的 stdio MCP)
    p_sl = sub.add_parser("spider-live",
                          help="把检索埋点实时直播到 prompt-spider-ui(需 Node 20+)")
    p_sl.add_argument("--repo", default=None,
                      help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_sl.add_argument("--spider-home", default=None,
                      help="prompt-spider-ui 克隆根, 默认探 KB_SPIDER_HOME/常见同级目录")
    p_sl.add_argument("--caller", default=None, help="只直播指定项目身份的检索")
    p_sl.add_argument("--max-sec", type=float, default=0.0,
                      help="运行上限秒数(0=常驻, 联调用)")

    # trace 独立解析: 不用 parents=[common](其 --repo 默认 "." 会静默失效);
    # 各子命令自定义 --repo, 缺省 None = 集中读 Agent-KB 仓根 kb_root()
    p_tr = sub.add_parser("trace")
    tr_sub = p_tr.add_subparsers(dest="trace_cmd", required=True)
    p_tl = tr_sub.add_parser("list")
    p_tl.add_argument("--repo", default=None,
                      help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_tl.add_argument("--caller", default=None)
    p_tl.add_argument("--since", default=None, help="YYYY-MM-DD")
    p_tl.add_argument("--zero-hit", action="store_true")
    p_tl.add_argument("--limit", type=int, default=30)
    p_ts = tr_sub.add_parser("show")
    p_ts.add_argument("id")
    p_ts.add_argument("--repo", default=None,
                      help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_te = tr_sub.add_parser("export")
    p_te.add_argument("id", nargs="?", help="trace id; 与 --latest 二选一")
    p_te.add_argument("--latest", action="store_true",
                      help="自动取最近一次检索(可配 --caller 限定 agent)")
    p_te.add_argument("--caller", default=None, help="仅与 --latest 联用")
    p_te.add_argument("--repo", default=None,
                      help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_te.add_argument("--format", default="spider", choices=["spider"])
    p_te.add_argument("-o", "--out", default=None, help="输出文件, 默认 <trace_id>.json")

    # FR-3.5 零命中反馈回路: 周报 = 零命中榜 + 消化率(唯一让命中率单调上升的机制)
    p_trp = tr_sub.add_parser("report", help="零命中周报(消化率+高频待消化词)")
    p_trp.add_argument("--repo", default=None,
                       help="Agent-KB 仓根(其下 traces/), 默认为本仓 kb_root()")
    p_trp.add_argument("--since", default=None, help="YYYY-MM-DD, 默认近 7 天")
    p_trp.add_argument("--caller", default=None)
    p_trp.add_argument("--format", default="md", choices=["md", "json"])

    args = ap.parse_args(argv)
    # trace 子命令 --repo 缺省 None(= kb_root()); 其余命令经 common 恒有默认 "."
    repo = Path(args.repo) if args.repo is not None else None

    if args.cmd == "new":
        if args.generated or args.body_file:
            # 门控路径强制 scope=project, 显式提示避免静默吞掉用户参数
            if args.scope != "project":
                print("note: generated entries are always scope=project", file=sys.stderr)
            body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else None
            e = create_draft(repo, type=args.type, domain=args.domain, title=args.title,
                             body=body, severity=args.severity,
                             agent_kbs=tuple(Path(p) for p in args.agent_kb))
        else:
            e = create_entry(repo, type=args.type, domain=args.domain, scope=args.scope,
                             title=args.title, generated=False, today=dt.date.today())
            if args.severity:
                cur = parse_entry(e.path)
                cur.fm["severity"] = args.severity
                e.path.write_text(dump_entry(cur), encoding="utf-8")
        print(e.path)
        return 0
    if args.cmd == "review":
        # 与 MCP kb_review 对齐: agent 自审 accepted 必须带 evidence
        # (gate 层拒绝 speculative, 但"空证据自审 accepted"仅在此工具面拦)
        if args.as_agent and args.to == "accepted" and not (args.evidence or "").strip():
            print("kb error: --as-agent --to accepted 需先完成自行验证并附 --evidence",
                  file=sys.stderr)
            return 1
        e = gate_review(repo, args.id, args.to, by="agent" if args.as_agent else None,
                        confidence=args.confidence, evidence=args.evidence)
        print(json.dumps({**e.fm, "path": str(e.path)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "set-scope":
        e = gate_set_scope(repo, args.id, args.scope)
        print(json.dumps({**e.fm, "path": str(e.path)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "export":
        print(export_entry(repo, Path(args.to_repo), args.id, to_scope=args.to_scope))
        return 0
    if args.cmd == "init":
        from kb.bootstrap import init_repo
        ak = Path(args.agent_kb[0]) if args.agent_kb else None
        info = init_repo(repo, ak, args.kb_dir, repo_name=args.repo_name,
                         mcp_name=args.mcp_name, force=args.force,
                         serve_url=args.serve_url, serve_token=args.token)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        print("next: 复核 `kb doctor --repo <kb载体目录>`; 再让 Agent 重载 MCP 配置",
              file=sys.stderr)
        return 0
    if args.cmd == "doctor":
        from kb.bootstrap import doctor as run_doctor
        from kb.bootstrap import doctor_exit_code, render_doctor
        ak = Path(args.agent_kb[0]) if args.agent_kb else None
        checks = run_doctor(repo, agent_kb=ak, current_python=args.current_python)
        print(render_doctor(checks))
        return doctor_exit_code(checks)
    if args.cmd == "lint":
        errs = lint_repo(repo, scope=args.scope, cross_repos=[Path(p) for p in args.agent_kb])
        base_path = Path(args.baseline) if args.baseline else repo / ".kb-lint-baseline"
        warns = [e for e in errs if e.startswith("warning: ")]
        hard = [e for e in errs if not e.startswith("warning: ")]
        if args.update_baseline:
            base_path.write_text("".join(w + "\n" for w in sorted(warns)), encoding="utf-8")
            print(f"baseline updated: {len(warns)} warnings -> {base_path}")
            for e in hard:
                print(e, file=sys.stderr)
            return 1 if hard else 0
        baseline: set[str] = set()
        if base_path.exists():
            baseline = {ln for ln in base_path.read_text(encoding="utf-8").splitlines() if ln}
        # 基线只豁免 warning(存量债); 新 warning(不在基线)在 strict 下即硬错误。
        # 基线内已修复的条目视为过期, 不阻断但提示收缩(--update-baseline 固化)
        new_warns = [w for w in warns if w not in baseline]
        fixed = sorted(baseline - set(warns))
        if fixed:
            print(f"baseline stale: {len(fixed)} 条已修复, 建议 --update-baseline 收缩")
        for e in warns:
            print(e)
        for e in hard:
            print(e, file=sys.stderr)
        if hard:
            return 1
        if args.strict and new_warns:
            for w in new_warns:
                print(f"strict: {w}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "index":
        # 目录显示名统一小写: 仓库显示名大小写(本地克隆 Agent-KB)不得进入 repo 字段,
        # 否则与已提交 index 的规范名(agent-kb)不一致, `index --check` 恒 stale
        repo_name = args.repo_name or repo.resolve().name.lower()
        if args.check:
            ok = check_indexes(repo, repo_name=repo_name)
            print("index up to date" if ok else "index stale")
            return 0 if ok else 1
        md, jl, dj = build_indexes(repo, repo_name=repo_name)
        print(f"wrote {md}\nwrote {jl}\nwrote {dj}")
        return 0
    if args.cmd == "search":
        t0 = time.perf_counter()
        layers_list = [repo] + [Path(p) for p in args.agent_kb]
        res, reports = search_layers_report(
            layers_list, type=args.type, domain=args.domain, tag=args.tag,
            scope=args.scope, status=args.status, confidence=args.confidence,
            query=args.query, limit=args.limit)
        if kbtrace.trace_enabled(cli_flag=args.trace_on):
            ev = kbtrace.build_search_event(
                trace_id=kbtrace.new_trace_id(), source="cli",
                caller_repo=repo.resolve().name.lower(), query=args.query,
                filters={"type": args.type, "domain": args.domain, "tag": args.tag,
                         "scope": args.scope, "status": args.status,
                         "confidence": args.confidence},
                limit=args.limit, reports=reports,
                returned=[r["id"] for r in res],
                duration_ms=round((time.perf_counter() - t0) * 1000),
                returned_chars=len(json.dumps(res, ensure_ascii=False)))
            kbtrace.append_event(ev)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "show":
        if args.agent_kb:
            got = get_layered([repo] + [Path(p) for p in args.agent_kb], args.id)
            if got is None:
                print(f"not found: {args.id}", file=sys.stderr)
                return 1
            print(got[0])
            return 0
        text = get_entry(repo, args.id)
        if not text:
            print(f"not found: {args.id}", file=sys.stderr)
            return 1
        print(text)
        return 0
    if args.cmd == "related":
        if args.agent_kb:
            print(json.dumps(related_layers([repo] + [Path(p) for p in args.agent_kb], args.id),
                             ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(related(repo, args.id), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "stat":
        if args.needs_scope:
            rows = needs_scope(repo)
            if args.format == "md":
                _md_cell = lambda s: str(s).replace("|", "\\|")
                print("| id | title | type | domain | summary |")
                print("| --- | --- | --- | --- | --- |")
                for r in rows:
                    print(f"| {r['id']} | {_md_cell(r['title'])} | {r['type']} | "
                          f"{','.join(r['domain'])} | {_md_cell(r['summary'])} |")
            else:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if args.due_review:
            print(json.dumps(due_review(repo, dt.date.today()), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(stat(repo), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "serve":
        from kb.serve import run as serve_run
        if args.install_autostart or args.uninstall_autostart:
            from kb import autostart
            try:
                if args.uninstall_autostart:
                    print(autostart.uninstall())
                else:
                    print(autostart.install(
                        Path(args.repo).resolve() if args.repo
                        else Path(__file__).resolve().parents[2],
                        args.port, args.bind, args.default_caller))
            except (RuntimeError, OSError) as exc:
                print(f"kb serve autostart: {exc}", file=sys.stderr)
                return 1
            return 0
        try:
            serve_run(Path(args.repo) if args.repo else None, port=args.port,
                      bind=args.bind, token=args.token,
                      default_caller=args.default_caller)
        except ValueError as exc:  # 红线: 非本机绑定无 token → 拒绝启动
            print(f"kb serve: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "web":
        from kb.launcher import open_panel
        url, mode = open_panel(args.port, repo=Path(args.repo) if args.repo else None,
                               caller=args.caller, all_projects=args.all,
                               no_browser=args.no_browser)
        if mode == "local-degraded":
            print("⚠ 已配置团队观测服务端但不可达, 已降级连接本机 serve(数据仅本机)",
                  file=sys.stderr)
        print(url)
        return 0
    if args.cmd == "spider-live":
        from kb.spider_live import run as live_run
        try:
            live_run(Path(args.repo) if args.repo else None,
                     spider_home=args.spider_home, caller=args.caller,
                     max_sec=args.max_sec)
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"kb spider-live: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "trace":
        # 未传 --repo 时 root=None → trace 层落到 kb_root(); 显式传入则生效
        root = Path(args.repo) if args.repo else None
        if args.trace_cmd == "export":
            from kb.spider_export import to_record
            if bool(args.id) == bool(args.latest):
                print("export: 需指定 <id> 或 --latest 之一(不可同给)", file=sys.stderr)
                return 2
            if args.id and args.caller:
                print("export: --caller 仅与 --latest 联用", file=sys.stderr)
                return 2
            if args.latest:
                newest, _, _ = kbtrace.read_traces(root=root, caller=args.caller,
                                                   limit=1)
                if not newest:
                    print("no trace records" + (f" for caller={args.caller}"
                                                if args.caller else ""), file=sys.stderr)
                    return 1
                args.id = newest[0]["trace_id"]
            ev = kbtrace.find_trace(args.id, root=root)
            if ev is None:
                print(f"trace not found: {args.id}", file=sys.stderr)
                return 1
            _, gets, _ = kbtrace.read_traces(root=root)
            rec = to_record(ev, [g for g in gets
                                 if g.get("trace_id") == args.id])
            out = Path(args.out) if args.out else Path(f"{args.id}.json")
            out.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(out)
            return 0
        if args.trace_cmd == "report":
            import datetime as _dt
            from kb import stats as kbstats
            since = args.since or (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
            searches, _, _ = kbtrace.read_traces(root=root, caller=args.caller)
            win = [s for s in searches if str(s.get("ts", ""))[:10] >= since]
            board = kbstats.zero_hit_board(win, limit=30)
            digested = [r for r in board if r["digested"]]
            rate = round(len(digested) / len(board), 4) if board else None
            if args.format == "json":
                print(json.dumps({"since": since, "zero_hit_queries": len(board),
                                  "digested": len(digested), "digest_rate": rate,
                                  "board": board}, ensure_ascii=False, indent=2))
                return 0
            print(f"# 零命中周报(自 {since}"
                  + (f" · caller={args.caller}" if args.caller else "") + ")")
            print(f"\n待消化 {len(board) - len(digested)} / 上榜 {len(board)}"
                  + (f" · 消化率 {rate * 100:.0f}%" if rate is not None else ""))
            todo = [r for r in board if not r["digested"]]
            if todo:
                print("\n高频待消化词(消化动作: 补 tags / 改 summary / 立新条 / 加 alias):")
                for r in todo:
                    print(f"- 「{r['query']}」×{r['count']} (caller={r['caller']}, "
                          f"最近 {r['last_ts'][:10]})")
            else:
                print("\n本窗口零命中已全部消化 ✅")
            return 0
        if args.trace_cmd == "show":
            ev = kbtrace.find_trace(args.id, root=root)
            if ev is None:
                print(f"trace not found: {args.id}", file=sys.stderr)
                return 1
            print(json.dumps(ev, ensure_ascii=False, indent=2))
            return 0
        searches, _, warns = kbtrace.read_traces(root=root, caller=args.caller,
                                                 since=args.since,
                                                 zero_hit=args.zero_hit,
                                                 limit=args.limit)
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        if not searches:
            print("暂无 trace 记录。开启方式: kb search --trace / 环境变量 KB_TRACE=1 / "
                  "仓根放置 .kb-trace 标记文件")
            return 0
        print(f"{'时间':<20} {'来源':<5} {'caller':<22} {'命中':>4}  query / trace_id")
        for s in searches:
            hits = len(s.get("returned", []))
            flag = " 0命中" if hits == 0 else f" {hits:>4}"
            print(f"{str(s.get('ts', ''))[:19]:<20} {s.get('source', ''):<5} "
                  f"{s.get('caller_repo', ''):<22}{flag}  "
                  f"{s.get('query') or '-'} / {s.get('trace_id')}")
        return 0
    if args.cmd == "promote":
        fm = promote(repo, args.id, args.to)
        print(json.dumps(fm, ensure_ascii=False, indent=2))
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK, 条目含 emoji 时 print 直接崩; 统一切 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return _dispatch(argv)
    except DuplicateCandidate as exc:
        print(json.dumps({"error": "duplicate", "candidates": exc.entries},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except (GateViolation, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"kb error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
