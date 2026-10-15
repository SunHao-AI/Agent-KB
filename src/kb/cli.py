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
    p_ss = sub.add_parser("set-scope", parents=[common])
    p_ss.add_argument("id"); p_ss.add_argument("scope", choices=["project", "stack", "universal"])
    p_ex = sub.add_parser("export", parents=[common])
    p_ex.add_argument("id"); p_ex.add_argument("--to-repo", required=True)
    p_ex.add_argument("--to-scope", required=True, choices=["stack", "universal"])

    p_tr = sub.add_parser("trace", parents=[common])
    tr_sub = p_tr.add_subparsers(dest="trace_cmd", required=True)
    p_tl = tr_sub.add_parser("list")
    p_tl.add_argument("--caller", default=None)
    p_tl.add_argument("--since", default=None, help="YYYY-MM-DD")
    p_tl.add_argument("--zero-hit", action="store_true")
    p_tl.add_argument("--limit", type=int, default=30)
    p_ts = tr_sub.add_parser("show")
    p_ts.add_argument("id")

    args = ap.parse_args(argv)
    repo = Path(args.repo)

    if args.cmd == "new":
        if args.generated or args.body_file:
            # 门控路径强制 scope=project, 显式提示避免静默吞掉用户参数
            if args.scope != "project":
                print("note: generated entries are always scope=project", file=sys.stderr)
            body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else None
            e = create_draft(repo, type=args.type, domain=args.domain, title=args.title,
                             body=body, agent_kbs=tuple(Path(p) for p in args.agent_kb))
        else:
            e = create_entry(repo, type=args.type, domain=args.domain, scope=args.scope,
                             title=args.title, generated=False, today=dt.date.today())
        print(e.path)
        return 0
    if args.cmd == "review":
        e = gate_review(repo, args.id, args.to)
        print(json.dumps({**e.fm, "path": str(e.path)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "set-scope":
        e = gate_set_scope(repo, args.id, args.scope)
        print(json.dumps({**e.fm, "path": str(e.path)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "export":
        print(export_entry(repo, Path(args.to_repo), args.id, to_scope=args.to_scope))
        return 0
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
                duration_ms=round((time.perf_counter() - t0) * 1000))
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
    if args.cmd == "trace":
        if args.trace_cmd == "show":
            ev = kbtrace.find_trace(args.id)
            if ev is None:
                print(f"trace not found: {args.id}", file=sys.stderr)
                return 1
            print(json.dumps(ev, ensure_ascii=False, indent=2))
            return 0
        searches, _, warns = kbtrace.read_traces(caller=args.caller, since=args.since,
                                                 zero_hit=args.zero_hit, limit=args.limit)
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
    try:
        return _dispatch(argv)
    except DuplicateCandidate as exc:
        print(json.dumps({"error": "duplicate", "candidates": exc.entries},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except (GateViolation, FileNotFoundError, ValueError) as exc:
        print(f"kb error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
