"""用户级配置 ~/.kb/config.toml(FR-2.5 令牌分发: 凭据永不入项目仓)。

格式为最小 TOML 子集([section] + key = "value" 行), 避免引入 toml 依赖:
    [serve]
    url   = "http://kb.internal:4320"
    token = "<团队实例令牌>"

    [ingest]
    url = "http://kb.internal:4320"      # 埋点直播上报目标(可空)

优先级: 环境变量(KB_INGEST_URL / KB_SERVE_URL / KB_SERVE_TOKEN)> 本文件。
"""
from __future__ import annotations

import os
from pathlib import Path


def config_path() -> Path:
    return Path.home() / ".kb" / "config.toml"


def parse_toml_subset(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    section = "_"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            out.setdefault(section, {})
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            v = v.split("#")[0].strip().strip('"').strip("'")
            out.setdefault(section, {})[k.strip()] = v
    return out


def read_config(path: Path | None = None) -> dict[str, dict[str, str]]:
    p = Path(path) if path else config_path()
    if not p.exists():
        return {}
    try:
        return parse_toml_subset(p.read_text(encoding="utf-8"))
    except OSError:
        return {}


def serve_target(path: Path | None = None) -> tuple[str | None, str | None]:
    """团队观测服务端 (url, token); 环境变量优先。都缺 → (None, None)=单人态。"""
    cfg = read_config(path).get("serve", {})
    url = os.environ.get("KB_SERVE_URL") or cfg.get("url") or None
    token = os.environ.get("KB_SERVE_TOKEN") or cfg.get("token") or None
    return url, token


def ingest_target(path: Path | None = None) -> tuple[str | None, str | None]:
    """埋点直播上报 (url, token); url 缺 → 不启用 ingest。"""
    cfg = read_config(path)
    url = os.environ.get("KB_INGEST_URL") or cfg.get("ingest", {}).get("url") or None
    token = os.environ.get("KB_INGEST_TOKEN") or cfg.get("serve", {}).get("token") or None
    return url, token


def write_serve_config(url: str, token: str | None = None,
                       path: Path | None = None) -> Path:
    """kb init --serve-url/--token 的落盘口: 只写用户级文件, 项目仓永不出现凭据。"""
    p = Path(path) if path else config_path()
    cfg = read_config(p)
    serve = cfg.setdefault("serve", {})
    serve["url"] = url
    if token:
        serve["token"] = token
    cfg.setdefault("ingest", {})["url"] = url
    lines = []
    for section in sorted(cfg):
        lines.append(f"[{section}]")
        for k, v in sorted(cfg[section].items()):
            lines.append(f'{k} = "{v}"')
        lines.append("")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
