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
import re
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
            v = v.strip()
            # 与写侧(write_serve_config 恒写 "值")对称: 引号值取到配对闭引号,
            # 闭引号后(含行内注释)丢弃; 引号内的 # 属值本身。旧实现无条件
            # split('#') 把引号内 # 也当注释截 → 含 # 的 URL 片段/令牌写进
            # config 再读出即损坏(第二十九轮实锤: 静默截掉的恰是凭据尾巴,
            # 401 无从排查)。仅无引号值才把 # 起视为注释(兼容手写)。
            if v.startswith('"'):
                # 闭引号必须跳过转义对 `\"`——朴素 find('"') 会被 `"a\"b"` 的
                # 转义引号提前闭合(第二十九轮对称面实锤)。未闭合 = 写侧损坏,
                # 抛 ValueError 由 read_config 整体降级为空: 坏文件绝不半解析
                # (静默截掉凭据尾巴比读不到更难排查)。
                m = re.match(r'"((?:[^"\\]|\\.)*)"', v)
                if not m:
                    raise ValueError(f"unterminated quote: {line!r}")
                # 闭引号后只允许空白或 # 注释; 其余(如旧版写坏的 `"a"b"` 的
                # 尾段 `b"`)一律视为损坏——绝不把 `"a"` 当 token 半解析出来
                tail = v[m.end():].strip()
                if tail and not tail.startswith("#"):
                    raise ValueError(f"junk after closing quote: {line!r}")
                # 单遍反转义(两步 replace 对 `\"` 与 `\\` 交叠的值会错序误还原;
                # 写侧只产出 \" 与 \\ 两种转义, 单反斜杠+原字符即还原)
                v = re.sub(r"\\(.)", lambda mo: mo.group(1), m.group(1))
            elif v.startswith("'"):
                end = v.find("'", 1)
                if end < 0:
                    raise ValueError(f"unterminated quote: {line!r}")
                v = v[1:end]
            else:
                v = v.split("#")[0].strip()
            out.setdefault(section, {})[k.strip()] = v
    return out


def read_config(path: Path | None = None) -> dict[str, dict[str, str]]:
    p = Path(path) if path else config_path()
    if not p.exists():
        return {}
    try:
        return parse_toml_subset(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError = 坏文件(引号未闭合等): 整体降级为空, 绝不半解析
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
            # 转义 \ 与 ", 与读侧配对闭引号+反转义对称; 旧版原样嵌入, 值含
            # 引号即产出 `token = "a"b"` 损坏文件(第二十九轮对称面快检实锤)
            esc = v.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{esc}"')
        lines.append("")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
