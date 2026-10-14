---
id: kb-20261013-984f
title: 'Pydantic v2 Settings `extra="forbid"` 默认值 + `restart: unless-stopped` 组合 =
  僵尸容器'
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-04'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# Pydantic v2 Settings `extra="forbid"` 默认值 + `restart: unless-stopped` 组合 = 僵尸容器

## 背景 / 现象

> 面向：`flysee_video_web` 后端（`compose.backend` service）+ workspace-wide `dev-all.ps1` 端口参数化脚本。修 [backend/core/config.py#L75](file:///d:/WorkPlace/Pycharm/flysee_video_web/backend/core/config.py#L75)。
**三态对照表**（v2 BaseSettings / BaseModel）：
| extra 值 | 行为 | 适用场景 |
|---|---|---|
| `forbid`（v2 **默认**，v1 非默认） | 任未声明字段触发 `ValidationError: Extra inputs are not permitted` | **安全模式**：strict API 请求 schema（写接口字段最小化），脱掉所有意外字段 |
| `ignore`（v2 非默认，v1 **默认**） | 未声明字段静默丢弃 | **env 注入应用**：Settings 一旦混入 docker exec / compose env_file 来源的"工具 env"键，必须 ignore；**读接口** schema |
| `allow` | 隐式接收 + 可 `model_extra` 字典般访问 | **开放 schema / ETL 中转**：API 回显含 unknown-field 原始载荷 |
- **写 Settings 注释前先工具化**：在 `tests/test_config.py` 跑"把工具 env 显式塞进 `os.environ` 再来构造 Settings" — 一次跑通就钉下行为，复发即回归。
- **修改 backend `Settings` 字段时**——加/删字段——必须**先 `docker compose up -d --force-recreate backend`** 而不是只 `restart`：除 `model_config` 外的字段声明不在 `model_dump` 之后的实例属性，live-reload 不存在，必须冷启动走 `__init__`。
- `dev-all.ps1` 一旦继续往 backend 容器注入新的工具 env 键，**先在 `tests/test_config.py` 加一个**对应的 `extra="ignore"` 测试，再进 backend 代码，避免"改完脚本部署时炸一次"。

## 根因

1. Pydantic v2 `BaseSettings` **默认 `extra='forbid'`**（Pydantic v1 是 `'ignore'`，v2 改为了 strict）。`dev-all.ps1`（workspace-wide，每 4 服务都要启动的口子）T01-T04 端口参数化把 `flysee_mysql_user`/`flysee_mysql_password`/`flysee_mysql_database`/`flysee_rabbitmq_containerport`/`flysee_media_rtmp_containerport`/`flysee_media_http_containerport`/`flysee_media_http_port` 等"工具 env"键**注入 backend 容器**（设计上供 `docker exec` 跨服务引用 + compose 内部 `${...}` 模板展开方便）——但这些键**不在 backend `Settings` 声明里**，于是 instance 构造时 ValidationError。

2. compose backend 服务的 `restart: unless-stopped` 默认 = 进程一 crash docker daemon 立刻 auto-restart。startup 期 ValidationError 又 100% 复现 → **restart 循环**永远到不了 `lifespan` 中段 `uvicorn.run(...)`。

3. 容器 exit status = 1 + auto-restart 时，`docker ps` 仍标 `Up`、`restart: unless-stopped` 让 status 字面在 healthy（上一轮的 healthcheck 结果残留），**容器层 DOM 完全看不出循环**。这是这个坑最毒的地方——网络层验证（端口扫、curl）永远是真相，**只看 `docker ps` 在 restart-unless-stopped + 启动期 crash 场景必然被误导**。

## 解决方案

```python

# backend/core/config.py  L73-77（修复后）

# bug 记录：dev-all.ps1 T01-T04 把 flysee_mysql_* / flysee_rabbitmq_* /

# flysee_media_rtmp_* / flysee_media_http_* 等端口/账号 env 注入 backend 容器，

# 这些字段不在本 Settings 声明，pydantic-settings 2 默认 extra='forbid' 触发

# "Extra inputs are not permitted" 启动失败。

model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

```

**一行**修：`Settings` 加 `extra="ignore"`。

## 验证

```python

# tests/test_config.py（新增）

import pytest

from pydantic import ValidationError

from pydantic_settings import BaseSettings, SettingsConfigDict

def test_settings_extras_is_ignore_when_injected(monkeypatch):

    """注入 dev-all.ps1 风格的“工具 env”键，断言 Settings 不抛 + 不挂属性。"""

    monkeypatch.setenv("flysee_mysql_user", "injected")

    monkeypatch.setenv("flysee_rabbitmq_containerport", "5672")

    from backend.core.config import get_settings

    s = get_settings()

    assert not hasattr(s, "flysee_mysql_user")

    assert not hasattr(s, "flysee_rabbitmq_containerport")

def test_forbid_mode_raises(monkeypatch):

    """反证：同一组键 + extra='forbid' 时确凿抛 ValidationError。"""

    monkeypatch.setenv("flysee_mysql_user", "injected")

    class Strict(BaseSettings):

        x: int = 1

        model_config = SettingsConfigDict(extra="forbid")

    with pytest.raises(ValidationError) as ei:

        Strict()

    assert "Extra inputs are not permitted" in str(ei.value)

```

容器层验通（py 代码改 + 1 行 model_config 后）：

```powershell

docker compose restart backend

# 等 12 秒（restart 过渡期），第一次 curl 经常 reset，重试一次

curl -i --max-time 5 http://127.0.0.1:17998/v1/system/logs/download

# 期望：HTTP/1.1 200（或 401/其他业务码）—— 已脱离 restart 循环

docker logs --tail 50 flysee-video-web-backend

# 期望：无 "Extra inputs are not permitted"，尾部看到 "Application startup complete"

```

## 适用边界

- 凡 Settings / BaseModel 一旦担心外部 env_file / 跨服务 env 注入，**主动 `extra="ignore"`** 并加注释说明原因；不要假定 v2 默认是宽松。

- compose `restart: unless-stopped` 服务的 startup 期 crash，**容器 status 看不出**，宁可加 `curl` 自检步骤；docker healthcheck 不要只验进程在不在（`pgrep`/`redis-cli ping` 这类），要验**业务端口可达**（如 `curl -fsS :17998/v1/system/logs/download`）。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「Pydantic v2 Settings `extra="forbid"` 默认值 + `restart: unless-stopped` 组合 = 僵尸容器」
