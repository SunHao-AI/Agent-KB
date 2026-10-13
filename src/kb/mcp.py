from __future__ import annotations
import argparse
from pathlib import Path
from kb.mcp_server import build_server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kb.mcp")
    ap.add_argument("--repo", default=".", help="repo root containing kb/")
    ap.add_argument("--agent-kb", action="append", default=[])
    ap.add_argument("--repo-name", default=None)
    a = ap.parse_args(argv)
    srv = build_server(Path(a.repo), [Path(p) for p in a.agent_kb], a.repo_name)
    srv.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
