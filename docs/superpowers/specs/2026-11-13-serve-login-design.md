# 观测面板登录体验（serve token 登录 + 配置回落）— 设计

- 日期：2026-11-13
- 状态：设计已确认，待实现
- 关联代码：`src/kb/serve.py`、`src/kb/cli.py`、`src/kb/launcher.py`、`src/kb/userconf.py`、`src/kb/web/index.html`

## 1. 背景与问题

观测面板（默认 `http://127.0.0.1:4320`）开启鉴权后：

1. 静态壳 `/` 免鉴权，但所有 `/api/*` 需要令牌；直接打开裸地址只会看到"需要访问令牌"文字横幅，**页面内没有输入口**。
2. 令牌只能通过 `kb web` 拼 `?token=` 或手动在 URL 加 `?token=` 传入；用户记不住，每次都要翻配置。
3. `/api/session` 种下的 `kb_tk` cookie **没有 Max-Age**，属会话级，关浏览器即失效，重开必然重新经历第 1 步。
4. `kb serve` 目前只读 `--token` / `KB_SERVE_TOKEN`，**不读** `~/.kb/config.toml`，配置里写了令牌也对 serve 无效。

## 2. 目标与非目标

**目标**

- 面板内提供令牌登录卡，输入后即可使用，无需手工改 URL。
- 令牌可在 `~/.kb/config.toml [serve].token` 固定，`kb serve` / `kb web` / 面板登录共用同一来源（**令牌值不变**）。
- 支持"记住我 30 天"，默认不勾；关浏览器重开不必重复输入。
- 提供退出/切换令牌入口。
- 局域网/团队共享场景下不降低安全性：令牌不进浏览器可读存储，登录失败有速率限制。

**非目标**

- 不做多用户账号体系、不做角色权限（仍为单一共享令牌）。
- 不改任何 `/api/*` 数据口径与埋点。
- 不引入 HTTPS（文档说明跨不可信网络需前置反代）。
- 不改 `~/.kb/config.toml` 文件格式。

## 3. 方案选择

| 方案 | 结论 |
| --- | --- |
| **服务端补登录面 + 配置回落**（本设计） | 采纳：复用现有 ticket/cookie 体系，令牌不进 JS 存储，可退出、可记住、可限流 |
| 前端 localStorage 存令牌 + 自动拼 `?token=` | 否决：令牌落在 JS 可读存储；与现有 cookie 体系并存产生两套登录态 |
| HTTP Basic Auth 原生弹窗 | 否决：无法退出/切换、文案不可控，且需把 `Authorization` 纳入 SSE 链路 |

## 4. 设计

### 4.1 配置来源

`kb serve` 令牌解析优先级（缺省保持"本机免鉴权"）：

```
--token  >  KB_SERVE_TOKEN  >  ~/.kb/config.toml [serve].token  >  空
```

- 实现：`token=a.token or userconf.serve_target()[1]`（`serve_target` 内部已是 env > config）。
- `kb web` 本机模式：解析到令牌时，拉起 serve 同时传 `--token`，并在打开 URL 上附 `token=`（与团队模式一致）。面板完成交换后 `replaceState` 抹掉明文（现有逻辑）。
- 配置格式不变，示例（写入用户级文件，绝不入项目仓）：

```toml
[serve]
token = "fly@@see"
```

### 4.2 服务端接口

| 接口 | 行为 |
| --- | --- |
| `POST /api/session`（新增） | body `{"token": "...", "remember": false}`；鉴权未开启 → 409 `{"error":"auth disabled"}`；失败 → 403 `{"error":"bad token"}`；成功 → 铸 ticket（沿用 64 上限票据池）+ `Set-Cookie: kb_tk=<ticket>; Path=/; HttpOnly; SameSite=Lax`，`remember=true` 时追加 `Max-Age=2592000`；返回 `{"ok": true, "remember": <bool>}` |
| `POST /api/logout`（新增） | 从票据池移除当前 cookie 对应 ticket，`Set-Cookie: kb_tk=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax`；始终 200 |
| `GET /api/session?ticket=...` | 保留（`kb web` 链接链路），比较改为 `hmac.compare_digest` |
| `GET /healthz` | 增加 `"auth": bool`（仅表示是否启用令牌，不泄露值） |
| `_authorized` | Bearer / `?token=` 兜底比较改为 `hmac.compare_digest` |

请求体处理遵循现有 `do_POST` 约定：**先读干请求体再回错误**（Windows 下未读 body 即关闭会 RST 吞掉响应）。body 上限 4 KiB，超限 413。

### 4.3 登录失败限流

- 维度：客户端 IP（`self.client_address[0]`），进程内存字典，上限 256 个 key（超出按最旧清理）。
- 规则：60 秒滑动窗口内已累计 5 次失败后，后续尝试直接 `429 {"error":"too many attempts"}` 并带 `Retry-After: <剩余整秒>`（前 5 次仍按 403 返回并计数）。
- 成功登录立即清零该 IP 记录；只统计失败，不统计成功请求。
- 重启清零可接受（非持久化，避免引入存储依赖）。

### 4.4 面板登录 UI

- 数据请求 401 时统一调用 `showLogin()`，渲染**居中遮罩卡**：
  - `type=password` 输入框（`autocomplete="current-password"`，首次自动聚焦）；
  - "记住我 30 天"复选框，**默认不勾**，勾选偏好存 `localStorage['kb.remember']`（只存布尔）；
  - 登录按钮（提交中禁用并显示"登录中…"）；
  - 令牌来源提示：`~/.kb/config.toml [serve].token` / `KB_SERVE_TOKEN` / `--token`；
  - 卡内错误行。
- 幂等：多路并发 401 只渲染一张卡；不提供关闭按钮。
- 提交成功 → `location.reload()`，让所有视图重新取数。
- `/healthz` 返回 `auth=true` 时，页头 `#conn` 旁显示"退出"按钮：`POST /api/logout` → 重载回登录卡。
- 保留 `?token=` 链路；交换失败时展示登录卡并提示"URL 中的令牌无效"，不再静默 401。

### 4.5 错误文案

| 状态 | 文案 |
| --- | --- |
| 403 | 令牌不正确，请核对 `~/.kb/config.toml [serve].token` 或启动参数 |
| 429 | 失败次数过多，请 N 秒后重试（取 `Retry-After`） |
| 409 | 当前服务未启用令牌鉴权 |
| 网络异常 | 无法连接服务端，请确认 `kb serve` 在运行 |

### 4.6 安全边界

- 令牌只出现在：`kb web` 初始 URL（交换后抹除）、登录请求体（不进 URL/历史/Referer）。
- cookie：HttpOnly + SameSite=Lax + Path=/；不设 `Secure`（内网 HTTP），文档明确"仅建议可信内网，跨网请前置 HTTPS 反代"。
- 失败文案统一"不正确"，不区分"无此令牌/令牌错误"。
- 退出只撤销当前会话 ticket，不影响其他设备/标签页已建立的会话。
- localStorage 只存"记住我"布尔偏好，令牌永不落 JS 可读存储。

## 5. 数据流

```
用户打开 → GET / (免鉴权壳)
  → GET /healthz (auth?)
  → GET /api/stats → 401 → showLogin()
  → 输入令牌 → POST /api/session {token, remember}
      ├ 200 + Set-Cookie(kb_tk…) → location.reload() → 数据正常
      ├ 403 → 卡内报错        ├ 429 → 倒计时提示      └ 409 → 提示鉴权未启用
  → 已登录后点"退出" → POST /api/logout → Set-Cookie(Max-Age=0) → 重载回登录卡
```

## 6. 兼容性

- 无令牌（本机单人态）：行为不变，不出现登录卡与退出按钮。
- 已持有有效 cookie 的会话（含会话 cookie 与 30 天 cookie）：不受影响。
- 已建立的 SSE 长连接不因退出被立即掐断；页面重载后按新 cookie 状态重新鉴权。
- `GET /api/session?ticket=`、`?token=` 兜底、Bearer：全部保留；仅比较方式改为常量时间。
- 不触碰 `stats.py` / 埋点 / 面板数据口径。

## 7. 测试

服务端（pytest）：

1. `POST /api/session` 正确令牌 → 200 且 `Set-Cookie` 含 `HttpOnly`、`SameSite=Lax`、无 `Max-Age`；
2. `remember=true` → `Set-Cookie` 含 `Max-Age=2592000`；
3. 错误令牌 → 403；连续 5 次 → 第 6 次 429 且带 `Retry-After`；成功后计数清零；
4. 未启用鉴权（无 token）→ 409；
5. `POST /api/logout` → 旧 cookie 再请求 `/api/stats` 得 401；
6. `GET /api/session?ticket=` 仍可用；错误 ticket 403；
7. `/healthz` 的 `auth` 标志与是否配置令牌一致；
8. 令牌解析优先级：`--token` > env > config（monkeypatch HOME 与 env）；
9. 请求体超 4 KiB → 413。

launcher：

10. 本机模式解析到 config 令牌时，`spawn_serve` 收到 `--token` 且返回值 URL 含 `token=`。

前端（无 JS 测试框架）：

11. HTTP 层断言 `Set-Cookie` 属性；浏览器手验三态：登录卡、错误提示、勾选"记住我"后的 cookie 有效期；页头"退出"仅在 `auth=true` 出现。

回归：全量 pytest；`kb lint` / `kb index --check` 不受影响。

## 8. 验收标准

- 直接打开 `http://127.0.0.1:4320`（不带 `?token=`）→ 看到登录卡，输入 `~/.kb/config.toml` 中的令牌后正常进面板。
- 勾选"记住我"后关闭浏览器再打开 → 免登录（30 天内）。
- 不勾选 → 关浏览器后需重新登录。
- 点"退出" → 立即回到登录卡，另一浏览器不受影响。
- 连续输错 5 次 → 提示 "N 秒后重试"。
- `kb serve` 不带 `--token`、无环境变量，仅配置里有令牌 → 鉴权生效。
- 无任何令牌来源 → 本机免鉴权，行为与现状一致。

## 9. 风险与取舍

- **局域网 HTTP 明文**：cookie 与令牌在网络上可被嗅探。已通过文档声明边界，不引入 TLS 复杂度。
- **共享令牌**：无法区分谁在登录，退出只影响本会话；符合当前单人令牌模型。
- **限流按 IP**：NAT 后多人共享出口 IP 时可能相互影响；阈值 5/60s 已较宽松。
- **remember 30 天**：共用电脑上等同长期免密；默认不勾，由用户显式选择。
