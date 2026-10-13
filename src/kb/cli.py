from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from kb.new_entry import create_entry
from kb.gate import (create_draft, review as gate_review,
                     set_scope as gate_set_scope, export_entry,
                     DuplicateCandidate, GateViolation)
from kb.layers import search_layers, get_layered, related_layers
from kb.lint import lint_repo
from kb.index import build_indexes, check_indexes
from kb.search import search
from kb.query import get_entry, related, stat, due_review, needs_scope
from kb.promote import promote


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
    p_idx = sub.add_parser("index", parents=[common])
    p_idx.add_argument("--check", action="store_true")
    p_idx.add_argument("--repo-name", default=None,
                       help="repo 名(写入索引 repo 字段), 默认取 --repo 目录名")

    p_s = sub.add_parser("search", parents=[common])
    for flag in ("type", "domain", "tag", "scope", "status", "confidence", "query"):
        p_s.add_argument(f"--{flag}", default=None)
    p_s.add_argument("--limit", type=int, default=20)

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
        print(json.dumps(gate_set_scope(repo, args.id, args.scope), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "export":
        print(export_entry(repo, Path(args.to_repo), args.id, to_scope=args.to_scope))
        return 0
    if args.cmd == "lint":
        errs = lint_repo(repo, scope=args.scope, cross_repos=[Path(p) for p in args.agent_kb])
        hard = [e for e in errs if not e.startswith("warning: ")]
        for e in errs:
            print(e, file=sys.stdout if e.startswith("warning: ") else sys.stderr)
        return 1 if hard else 0
    if args.cmd == "index":
        repo_name = args.repo_name or repo.resolve().name
        if args.check:
            ok = check_indexes(repo, repo_name=repo_name)
            print("index up to date" if ok else "index stale")
            return 0 if ok else 1
        md, jl, dj = build_indexes(repo, repo_name=repo_name)
        print(f"wrote {md}\nwrote {jl}\nwrote {dj}")
        return 0
    if args.cmd == "search":
        if args.agent_kb:
            layers = [repo] + [Path(p) for p in args.agent_kb]
            res = search_layers(layers, type=args.type, domain=args.domain, tag=args.tag,
                                scope=args.scope, status=args.status,
                                confidence=args.confidence, query=args.query, limit=args.limit)
        else:
            res = search(repo, type=args.type, domain=args.domain, tag=args.tag,
                         scope=args.scope, status=args.status, confidence=args.confidence,
                         query=args.query, limit=args.limit)
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
