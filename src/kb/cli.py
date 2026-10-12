from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from kb.new_entry import create_entry
from kb.lint import lint_repo
from kb.index import build_indexes, check_indexes
from kb.search import search
from kb.query import get_entry, related, stat, due_review
from kb.promote import promote


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kb")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="repo root containing kb/")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", parents=[common])
    p_new.add_argument("type")
    p_new.add_argument("--domain", required=True)
    p_new.add_argument("--scope", required=True)
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--generated", action="store_true")

    sub.add_parser("lint", parents=[common]).add_argument("--scope", default="project")
    p_idx = sub.add_parser("index", parents=[common])
    p_idx.add_argument("--check", action="store_true")

    p_s = sub.add_parser("search", parents=[common])
    for flag in ("type", "domain", "tag", "scope", "status", "confidence", "query"):
        p_s.add_argument(f"--{flag}", default=None)
    p_s.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", parents=[common]); p_show.add_argument("id")
    p_rel = sub.add_parser("related", parents=[common]); p_rel.add_argument("id")
    p_stat = sub.add_parser("stat", parents=[common]); p_stat.add_argument("--due-review", action="store_true")
    p_pro = sub.add_parser("promote", parents=[common]); p_pro.add_argument("id"); p_pro.add_argument("--to", required=True)

    args = ap.parse_args(argv)
    repo = Path(args.repo)

    if args.cmd == "new":
        e = create_entry(repo, type=args.type, domain=args.domain, scope=args.scope,
                         title=args.title, generated=args.generated, today=dt.date.today())
        print(e.path)
        return 0
    if args.cmd == "lint":
        errs = lint_repo(repo, scope=args.scope)
        for e in errs:
            print(e, file=sys.stderr)
        return 1 if errs else 0
    if args.cmd == "index":
        if args.check:
            ok = check_indexes(repo)
            print("index up to date" if ok else "index stale")
            return 0 if ok else 1
        md, jl, dj = build_indexes(repo)
        print(f"wrote {md}\nwrote {jl}\nwrote {dj}")
        return 0
    if args.cmd == "search":
        res = search(repo, type=args.type, domain=args.domain, tag=args.tag,
                     scope=args.scope, status=args.status, confidence=args.confidence,
                     query=args.query, limit=args.limit)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "show":
        text = get_entry(repo, args.id)
        print(text if text else f"not found: {args.id}")
        return 0 if text else 1
    if args.cmd == "related":
        print(json.dumps(related(repo, args.id), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "stat":
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


if __name__ == "__main__":
    raise SystemExit(main())
