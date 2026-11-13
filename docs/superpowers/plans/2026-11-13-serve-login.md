# 观测面板登录体验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让观测面板能在页面内输入令牌登录，并让 `kb serve` 从 `~/.kb/config.toml [serve].token` 取令牌，支持"记住我 30 天"与退出。

**Architecture:** 复用现有 ticket + HttpOnly cookie 鉴权：新增 `POST /api/session`（JSON body 换 cookie）与 `POST /api/logout`（撤销票据），面板 401 时渲染登录卡；令牌解析统一收敛到 `serve.resolve_token()`（CLI > env > 用户配置），`kb web` 本机模式同步带令牌；登录失败按 IP 限流。

**Tech Stack:** Python 3.12 标准库（`http.server`/`hmac`/`secrets`）、pytest、原生 JS（无构建）。

## Global Constraints

- 规格来源：`docs/superpowers/specs/2026-11-13-serve-login-design.md`，逐条对齐，不扩大范围。
- 令牌值不变；不新增依赖；不改 `~/.kb/config.toml` 格式。
- Windows PowerShell 5：命令分隔用 `;`，禁止 `&&`。
- 跑全量测试前清环境干扰：`$env:KB_SERVE_TOKEN=$null; $env:KB_SPIDER_HOME=$null`。
- 只允许重启 `127.0.0.1:4320` 回环实例；**严禁**操作/重启 `0.0.0.0:4320`（属另一会话）。
- 不提交 `traces/*.jsonl`、`traces/metrics/`；不推送远端。
- 面板与注释文案用中文。

---

### Task 1: 令牌解析回落用户配置

**Files:**
- Modify: `src/kb/serve.py:1162-1177`（新增 `resolve_token`，`run` 不变）、`src/kb/serve.py:1215-1218`（main 调用）
- Test: `tests/test_stats_serve.py`（文件末尾追加）

**Interfaces:**
- Produces: `serve.resolve_token(cli_token: str | None = None) -> str | None`，优先级 `--token` > `KB_SERVE_TOKEN` > `~/.kb/config.toml [serve].token` > `None`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_stats_serve.py` 末尾追加：

```python
def test_resolve_token_priority(monkeypatch, tmp_path):
    """spec §4.1: --token > env > config, 缺省 None(本机免鉴权)。"""
    from kb import serve, userconf

    cfg = tmp_path / "config.toml"
    cfg.write_text('[serve]\ntoken = "cfg-tok"\n', encoding="utf-8")
    monkeypatch.setattr(userconf, "config_path", lambda: cfg)
    monkeypatch.delenv("KB_SERVE_TOKEN", raising=False)

    assert serve.resolve_token(None) == "cfg-tok"
    monkeypatch.setenv("KB_SERVE_TOKEN", "env-tok")
    assert serve.resolve_token(None) == "env-tok"
    assert serve.resolve_token("cli-tok") == "cli-tok"

    monkeypatch.delenv("KB_SERVE_TOKEN", raising=False)
    cfg.unlink()
    assert serve.resolve_token(None) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_serve.py::test_resolve_token_priority -v`
Expected: FAIL — `AttributeError: module 'kb.serve' has no attribute 'resolve_token'`

- [ ] **Step 3: 最小实现**

在 `src/kb/serve.py` 的 `run()` 之前插入：

```python
def resolve_token(cli_token: str | None = None) -> str | None:
    """令牌解析唯一入口(spec §4.1): --token > KB_SERVE_TOKEN > 用户配置。

    配置来源是 `~/.kb/config.toml [serve].token`, 由 userconf.serve_target 统一读取;
    缺省 None 表示本机单人态免鉴权(行为不变)。
    """
    from kb import userconf
    return cli_token or userconf.serve_target()[1] or None
```

把 `main()` 里的：

```python
            token=a.token or os.environ.get("KB_SERVE_TOKEN") or None,
```

改为：

```python
            token=resolve_token(a.token),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_stats_serve.py::test_resolve_token_priority -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/kb/serve.py tests/test_stats_serve.py
git commit -m "feat(serve): 令牌回落到用户配置(~/.kb/config.toml)"
```

---

### Task 2: 登录/退出接口、限流与 auth 标志

**Files:**
- Modify: `src/kb/serve.py:293-311`（`_authorized` 常量时间比较）、`src/kb/serve.py:313-337`（`do_POST` 路由登录/退出）、`src/kb/serve.py:390-392`（`/healthz` 加 auth）、`src/kb/serve.py:399-416`（GET session 比较）、`src/kb/serve.py:599-617`（server 字段）
- Test: `tests/test_stats_serve.py:407-421`（helper 扩展）+ 末尾追加用例

**Interfaces:**
- Consumes: `serve.resolve_token`（Task 1，不直接调用）。
- Produces: `POST /api/session` JSON `{"token": str, "remember": bool}` → 200 `{"ok": true, "remember": bool}` + `Set-Cookie: kb_tk=<ticket>; Path=/; HttpOnly; SameSite=Lax[; Max-Age=2592000]`；403/409/429；`POST /api/logout` → 200 且清 cookie；`/healthz` 增 `auth: bool`。

- [ ] **Step 1: 扩展测试 helper（先改测试基础设施）**

把 `tests/test_stats_serve.py:407-413` 的 `_get_url` 改为支持 cookie，并新增 `_post_json`：

```python
def _get_url(url, token=None, cookie=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def _post_json(url, payload, cookie=None):
    """POST JSON, 非 2xx 也返回 (status, body, headers)。"""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()), dict(e.headers)
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_stats_serve.py` 末尾追加：

```python
def test_login_session_cookie(tmp_path):
    """spec §4.2/§4.6: 登录成功种 HttpOnly 会话 cookie, 默认无 Max-Age。"""
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        st, body, hd = _post_json(f"{base}/api/session", {"token": "s3cret"})
        assert st == 200 and body["ok"] is True
        ck = hd["Set-Cookie"]
        assert "kb_tk=" in ck and "HttpOnly" in ck and "SameSite=Lax" in ck
        assert "Max-Age" not in ck
        cookie = ck.split(";")[0]
        st2, _ = _get_url(f"{base}/api/stats", cookie=cookie)
        assert st2 == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_login_remember_sets_max_age(tmp_path):
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        st, body, hd = _post_json(
            f"{base}/api/session", {"token": "s3cret", "remember": True})
        assert st == 200 and body["remember"] is True
        assert "Max-Age=2592000" in hd["Set-Cookie"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_login_bad_token_and_lockout(tmp_path):
    """spec §4.3: 前 5 次 403 计数, 第 6 次 429 + Retry-After; 成功后清零。"""
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        for _ in range(5):
            st, _, _ = _post_json(f"{base}/api/session", {"token": "nope"})
            assert st == 403
        st, _, hd = _post_json(f"{base}/api/session", {"token": "nope"})
        assert st == 429 and int(hd["Retry-After"]) >= 1
    finally:
        srv.shutdown()
        srv.server_close()

    srv, base = _serve(tmp_path, token="s3cret")
    try:
        for _ in range(4):
            _post_json(f"{base}/api/session", {"token": "nope"})
        st, _, _ = _post_json(f"{base}/api/session", {"token": "s3cret"})
        assert st == 200
        st, _, _ = _post_json(f"{base}/api/session", {"token": "nope"})
        assert st == 403  # 成功已清零, 未触发限流
    finally:
        srv.shutdown()
        srv.server_close()


def test_login_auth_disabled_returns_409(tmp_path):
    srv, base = _serve(tmp_path)  # 无 token = 免鉴权
    try:
        st, body, _ = _post_json(f"{base}/api/session", {"token": "x"})
        assert st == 409 and "auth disabled" in body["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_logout_revokes_cookie(tmp_path):
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        _, _, hd = _post_json(f"{base}/api/session", {"token": "s3cret"})
        cookie = hd["Set-Cookie"].split(";")[0]
        st, _ = _get_url(f"{base}/api/stats", cookie=cookie)
        assert st == 200
        st, body, hd2 = _post_json(f"{base}/api/logout", {}, cookie=cookie)
        assert st == 200 and "Max-Age=0" in hd2["Set-Cookie"]
        try:
            _get_url(f"{base}/api/stats", cookie=cookie)
            raise AssertionError("退出后旧 cookie 应 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        srv.shutdown()
        srv.server_close()


def test_login_body_too_large(tmp_path):
    """spec §4.2: 登录 body 上限 4 KiB, 超限 413。"""
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        big = json.dumps({"token": "x" * 5000}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/session", data=big, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("超限 body 应 413")
        except urllib.error.HTTPError as e:
            assert e.code == 413
    finally:
        srv.shutdown()
        srv.server_close()


def test_healthz_reports_auth_flag(tmp_path):
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        st, body = _get_url(f"{base}/healthz")
        assert st == 200 and body["auth"] is True
    finally:
        srv.shutdown()
        srv.server_close()
    srv, base = _serve(tmp_path)
    try:
        _, body = _get_url(f"{base}/healthz")
        assert body["auth"] is False
    finally:
        srv.shutdown()
        srv.server_close()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_serve.py -k "login or logout or healthz_reports_auth" -v`
Expected: FAIL — `/api/session` POST 返回 404 `not found`

- [ ] **Step 4: 实现服务端**

4a. `src/kb/serve.py` 顶部导入区加 `import hmac`（`secrets` 已按需局部导入，不动）。

4b. `ServeServer.__init__`（`self.tickets` 之后，约 616 行）追加：

```python
        # 登录失败限流(spec §4.3): 每 IP 60s 滑动窗口, 有界防内存滥用
        self.login_fail: dict[str, list[float]] = {}
        self.login_lock = threading.Lock()
```

4c. 在 `_authorized` 末尾把：

```python
        return got == tok
```

改为：

```python
        return _same_secret(got, tok)
```

并在模块级（`_Handler` 类之前）新增：

```python
_LOGIN_WINDOW = 60.0
_LOGIN_MAX_FAILS = 5
_LOGIN_MAX_IPS = 256
_COOKIE_ATTRS = "Path=/; HttpOnly; SameSite=Lax"


def _same_secret(a: str, b: str) -> bool:
    """常量时间比较(非 ASCII 也安全): 避免逐字符短路泄露令牌前缀。"""
    try:
        return hmac.compare_digest(a, b)
    except TypeError:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
```

4d. `do_POST` 顶部（`if u.path != "/api/ingest":` 之前）插入路由：

```python
        if u.path == "/api/session":
            self._login(raw, n)
            return
        if u.path == "/api/logout":
            self._logout()
            return
```

4e. 在 `_Handler` 内新增三个方法（放在 `do_POST` 之后）：

```python
    def _login(self, raw: bytes, n: int) -> None:
        """JSON body 登录(spec §4.2): 令牌只进请求体, 不进 URL/历史/Referer。"""
        srv = self.server  # type: ignore[attr-defined]
        if not srv.token:
            self._json({"error": "auth disabled"}, 409)
            return
        if n <= 0:
            self._json({"error": "bad body"}, 400)
            return
        if n > 4096:
            self._json({"error": "body too large"}, 413)
            return
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "bad json"}, 400)
            return
        tok = body.get("token") if isinstance(body, dict) else None
        remember = bool(body.get("remember")) if isinstance(body, dict) else False
        ip = self.client_address[0] if self.client_address else "?"
        wait = self._login_wait(srv, ip)
        if wait:
            self._json({"error": "too many attempts"}, 429,
                       extra={"Retry-After": str(wait)})
            return
        if not isinstance(tok, str) or not _same_secret(tok, srv.token):
            self._record_login_fail(srv, ip)
            self._json({"error": "bad token"}, 403)
            return
        with srv.login_lock:
            srv.login_fail.pop(ip, None)
        import secrets as _secrets
        t = _secrets.token_urlsafe(32)
        with srv.login_lock:
            if len(srv.tickets) >= 64:
                srv.tickets.clear()
            srv.tickets.add(t)
        ck = f"kb_tk={t}; {_COOKIE_ATTRS}"
        if remember:
            ck += "; Max-Age=2592000"
        self._json({"ok": True, "remember": remember}, extra={"Set-Cookie": ck})

    def _login_wait(self, srv, ip: str) -> int:
        """返回需要等待的整秒; 0 表示放行。只清理/统计, 不改写超出窗口的记录。"""
        now = time.monotonic()
        with srv.login_lock:
            times = [t for t in srv.login_fail.get(ip, [])
                     if now - t < _LOGIN_WINDOW]
            if times:
                srv.login_fail[ip] = times
            else:
                srv.login_fail.pop(ip, None)
            if len(times) >= _LOGIN_MAX_FAILS:
                return max(1, int(_LOGIN_WINDOW - (now - times[0])) + 1)
            return 0

    def _record_login_fail(self, srv, ip: str) -> None:
        now = time.monotonic()
        with srv.login_lock:
            times = [t for t in srv.login_fail.get(ip, [])
                     if now - t < _LOGIN_WINDOW]
            times.append(now)
            srv.login_fail[ip] = times
            if len(srv.login_fail) > _LOGIN_MAX_IPS:
                srv.login_fail.pop(next(iter(srv.login_fail)), None)

    def _logout(self) -> None:
        """撤销当前 cookie 的票据(spec §4.2): 只影响本会话, 其他设备不动。"""
        srv = self.server  # type: ignore[attr-defined]
        ck = self.headers.get("Cookie", "")
        for part in ck.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "kb_tk" and v:
                with srv.login_lock:
                    srv.tickets.discard(v)
        self._json({"ok": True}, extra={
            "Set-Cookie": f"kb_tk=; {_COOKIE_ATTRS}; Max-Age=0"})
```

4f. `/healthz` 改为：

```python
            self._json({"ok": True, "schema": kbtrace.SCHEMA,
                        "auth": bool(srv.token)})
```

4g. `GET /api/session` 的 `tokq != srv.token` 改为 `not _same_secret(tokq, srv.token)`：

```python
            if not srv.token or not _same_secret(tokq, srv.token):
```

- [ ] **Step 5: 跑新测试**

Run: `python -m pytest tests/test_stats_serve.py -k "login or logout or healthz_reports_auth" -v`
Expected: 全部 PASS

- [ ] **Step 6: 跑既有鉴权回归**

Run: `python -m pytest tests/test_stats_serve.py -k "token or session" -v`
Expected: 全部 PASS（含旧 `test_serve_token_enforced`、`test_serve_session_cookie_replaces_token_in_url`）

- [ ] **Step 7: 提交**

```powershell
git add src/kb/serve.py tests/test_stats_serve.py
git commit -m "feat(serve): 登录/退出接口+失败限流+healthz auth 标志"
```

---

### Task 3: 面板登录卡与退出入口

**Files:**
- Modify: `src/kb/web/index.html`（样式区、`apiUrl` 附近、`loadStats` 401、feed 401、boot 交换块、`#conn`）
- Test: `tests/test_stats_serve.py::test_panel_inline_script_parses`（既有，自动覆盖语法）

**Interfaces:**
- Consumes: `POST /api/session`、`POST /api/logout`、`/healthz.auth`（Task 2）。
- Produces: 全局 `showLogin(msg?: string)`；`localStorage['kb.remember']` 只存 `'0'/'1'`。

- [ ] **Step 1: 加登录卡样式**

在 `src/kb/web/index.html` 的 `.banner{...}` 规则（约 106 行）之后插入：

```css
  .login-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);backdrop-filter:blur(2px);
        display:flex;align-items:center;justify-content:center;z-index:9999}
  .login-card{background:var(--panel);border:1px solid var(--bd);border-radius:12px;
        padding:22px 24px;width:min(92vw,360px);display:flex;flex-direction:column;gap:10px;
        box-shadow:0 20px 60px rgba(0,0,0,.35)}
  .login-card h3{margin:0;font-size:16px}
  .login-card .tip{margin:0;font-size:12px;color:var(--dim,#8b98ab);line-height:1.5}
  .login-card input[type=password]{width:100%;padding:9px 10px;border:1px solid var(--bd);
        border-radius:8px;background:var(--panel2);color:var(--tx);font:inherit}
  .login-card label{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--dim,#8b98ab)}
  .login-card button{padding:9px 12px;border:1px solid var(--bd);border-radius:8px;
        background:var(--panel2);color:var(--tx);font:inherit;cursor:pointer}
  .login-card button:disabled{opacity:.6;cursor:default}
  .login-err{color:#f34a87;font-size:12px;min-height:16px}
```

- [ ] **Step 2: 加 `showLogin` 与登录态初始化**

在 `const tk0=...`（约 295 行）之后、`function apiUrl`（约 376 行）之前插入：

```js
let loginShown=false, urlTokenBad=false;
function showLogin(msg){
  if(loginShown)return; loginShown=true;
  const m=document.createElement('div'); m.className='login-mask';
  const remember=localStorage.getItem('kb.remember')==='1';
  m.innerHTML=`<form class="login-card" id="loginForm">
    <h3>需要访问令牌</h3>
    <p class="tip">令牌来源: <code>~/.kb/config.toml [serve].token</code>、
      <code>KB_SERVE_TOKEN</code> 或 <code>--token</code></p>
    <input id="loginTok" type="password" autocomplete="current-password"
      placeholder="输入访问令牌" required>
    <label><input type="checkbox" id="loginRemember"${remember?' checked':''}>
      记住我 30 天</label>
    <button type="submit">登录</button>
    <div class="login-err" id="loginErr">${esc(msg||'')}</div>
  </form>`;
  document.body.appendChild(m);
  $('loginTok').focus();
  $('loginForm').addEventListener('submit', async e=>{
    e.preventDefault();
    const tk=$('loginTok').value.trim(), rm=$('loginRemember').checked;
    const btn=e.target.querySelector('button');
    btn.disabled=true; btn.textContent='登录中…';
    try{
      const r=await fetch('/api/session',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({token:tk,remember:rm})});
      if(r.ok){localStorage.setItem('kb.remember',rm?'1':'0');location.reload();return;}
      $('loginErr').textContent = r.status===429
        ? `失败次数过多，请 ${r.headers.get('Retry-After')||'稍'} 秒后重试`
        : r.status===409 ? '当前服务未启用令牌鉴权'
        : '令牌不正确，请核对配置或启动参数';
    }catch(_){ $('loginErr').textContent='无法连接服务端，请确认 kb serve 在运行'; }
    btn.disabled=false; btn.textContent='登录';
  });
}
async function initAuth(){
  try{
    const d=await (await fetch('/healthz')).json();
    if(!d.auth)return;
    const b=document.createElement('button');
    b.textContent='退出'; b.id='logoutBtn';
    b.style.cssText='margin-left:8px;padding:2px 8px;border:1px solid var(--bd);'+
      'border-radius:6px;background:var(--panel2);color:var(--tx);cursor:pointer;font:inherit';
    b.onclick=async()=>{ try{await fetch('/api/logout',{method:'POST'});}catch(_){}
      location.reload(); };
    $('conn').after(b);
  }catch(_){}
}
```

- [ ] **Step 3: 让所有 401 收敛到登录卡**

3a. `loadStats` 的 401 分支（约 715 行）改为：

```js
    if(r.status===401){ showLogin(urlTokenBad?'URL 中的令牌无效':''); return; }
```

3b. 检索流 401 分支（约 1021 行）改为：

```js
      if(r.status===401){ showLogin(urlTokenBad?'URL 中的令牌无效':''); return; }
```

3c. callers（约 840 行）里 `if(r.status===401)return;` 改为：

```js
      if(r.status===401){ showLogin(urlTokenBad?'URL 中的令牌无效':''); return; }
```

3d. 在 boot 的 `?token=` 交换块（函数体内以 `if(tk0)` 开头，约 1515 行）失败分支标记：

```js
    if(!r.ok) urlTokenBad=true;
```

3e. 在 boot 末尾调用 `initAuth();`（与首次 `loadStats()` 同级）。

- [ ] **Step 4: 语法与面板回归**

Run: `python -m pytest tests/test_stats_serve.py -k "panel or inline_script" -v`
Expected: PASS（含 `test_panel_inline_script_parses`；无 node 则 skip）

- [ ] **Step 5: 提交**

```powershell
git add src/kb/web/index.html
git commit -m "feat(panel): 页面登录卡+记住我+退出入口"
```

---

### Task 4: kb web 本机模式带令牌

**Files:**
- Modify: `src/kb/launcher.py:115-127`、`src/kb/launcher.py:135-138`
- Test: `tests/test_stats_serve.py` 末尾追加

**Interfaces:**
- Consumes: `userconf.serve_target() -> tuple[str | None, str | None]`（已有）。
- Produces: 本机模式 URL 在解析到令牌时附 `token=`；代拉起 serve 时传同一令牌。

- [ ] **Step 1: 写失败测试**

在 `tests/test_stats_serve.py` 末尾追加：

```python
def test_open_panel_local_carries_config_token(monkeypatch):
    """spec §4.1: 本机模式解析到令牌时, URL 带 token 且代拉起 serve 收到同一令牌。"""
    from kb import launcher, userconf

    seen = {}
    monkeypatch.setattr(userconf, "serve_target", lambda path=None: (None, "cfg-tok"))
    monkeypatch.setattr(launcher, "probe_http", lambda *a, **k: False)
    seq = iter([False, True])
    monkeypatch.setattr(launcher, "probe_port", lambda *a, **k: next(seq))
    monkeypatch.setattr(launcher, "spawn_serve",
                        lambda root, port, caller, token=None: seen.update(token=token))
    url, mode = launcher.open_panel(4320, caller=None, no_browser=True)
    assert seen["token"] == "cfg-tok"
    assert mode == "local" and _qs_of(url).get("token") == "cfg-tok"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_serve.py::test_open_panel_local_carries_config_token -v`
Expected: FAIL — `seen` 为空（`spawn_serve` 收到 `None`）且 URL 无 `token`

- [ ] **Step 3: 实现**

`launcher.open_panel` 中，`team_url, team_token = serve_target()` 之后统一解析一次：

```python
    team_url, team_token = serve_target()
    tok = team_token or token
```

把 `if team_url and probe_http(team_url, team_token):` 分支里的 `tok = team_token or token` 删掉（已上移）。

把 `spawn_serve(root, port, resolved, token=token)` 改为：

```python
        spawn_serve(root, port, resolved, token=tok)
```

在 `local_params = list(params)` 之后追加：

```python
    if tok:
        local_params.append(("token", tok))
```

- [ ] **Step 4: 跑新旧相关测试**

Run: `python -m pytest tests/test_stats_serve.py -k "open_panel" -v`
Expected: 全部 PASS（含既有 token 特殊字符、degraded 两个用例）

- [ ] **Step 5: 提交**

```powershell
git add src/kb/launcher.py tests/test_stats_serve.py
git commit -m "feat(launcher): 本机模式从配置取令牌并随 URL 传入"
```

---

### Task 5: 文档、重启服务与浏览器验收

**Files:**
- Modify: `README.md:110-140`、`USAGE.md:165-200`

**Interfaces:**
- Consumes: 全部前序任务。

- [ ] **Step 1: 更新 README「观测面板」**

在 `README.md` 的 `KB_SERVE_TOKEN` / `KB_INGEST_URL` 说明段（约 126 行）后补一段：

```markdown
鉴权令牌可用三种方式提供（优先级从高到低）：`kb serve --token`、环境变量
`KB_SERVE_TOKEN`、用户级配置 `~/.kb/config.toml`：

```toml
[serve]
token = "你的令牌"
```

配置里只需写一次，`kb serve` / `kb web` 都会读取。直接打开面板（不带 `?token=`）
会看到登录卡，可勾选"记住我 30 天"；页头"退出"可撤销当前会话。cookie 为
HttpOnly + SameSite=Lax，令牌不进浏览器存储。局域网共享请只在可信内网使用：
HTTP 明文传输，跨不可信网络需前置 HTTPS 反向代理。
```

- [ ] **Step 2: 更新 USAGE「观测面板」**

在 `USAGE.md` 第 9 节（约 195 行）后追加：

```markdown
### 登录与令牌

`kb serve` 的令牌解析顺序：`--token` > `KB_SERVE_TOKEN` > `~/.kb/config.toml`
的 `[serve] token`。三者都没有时本机免鉴权（单人态）。

打开面板若显示登录卡，输入同一令牌即可；勾选"记住我 30 天"后关闭浏览器不必
重输（cookie 为 HttpOnly，JS 读不到）。顶部"退出"只撤销当前会话，不影响其他
设备。连续输错 5 次会限流 60 秒。
```

- [ ] **Step 3: 重启本机 serve（只动回环实例）**

先确认 4320 的监听地址，并确认配置里已有令牌（否则重启后鉴权会关闭）：

```powershell
$p = Get-NetTCPConnection -LocalPort 4320 -State Listen
$p | Select-Object LocalAddress,OwningProcess
if (($p.LocalAddress | Select-Object -Unique) -ne '127.0.0.1') { throw '非回环实例, 停止操作' }
Select-String -Path "$HOME\.kb\config.toml" -Pattern 'token' -ErrorAction SilentlyContinue
```

若配置里没有令牌且 `$env:KB_SERVE_TOKEN` 为空，**停下来向用户索取现有令牌并写入配置**，不要自行猜测/生成（会改变他人正在用的凭据）。

```powershell
Stop-Process -Id $p.OwningProcess
Start-Process powershell -WindowStyle Hidden -WorkingDirectory "d:\WorkPlace\Pycharm\Agent-KB" `
  -ArgumentList '-NoProfile','-Command','kb serve --port 4320'
```

- [ ] **Step 4: HTTP 验收**

```powershell
(Invoke-WebRequest http://127.0.0.1:4320/healthz -UseBasicParsing).Content
```

Expected: JSON 含 `"auth":true`（前提：配置/env 里有令牌）。

```powershell
$tok = $env:KB_SERVE_TOKEN
Invoke-WebRequest http://127.0.0.1:4320/api/session -Method POST -UseBasicParsing `
  -ContentType application/json -Body (@{token=$tok} | ConvertTo-Json) |
  Select-Object StatusCode,@{n='SetCookie';e={$_.Headers['Set-Cookie']}}
```

Expected: `200`，`Set-Cookie` 含 `HttpOnly`、`SameSite=Lax`、无 `Max-Age`。

- [ ] **Step 5: 浏览器验收**

打开 `http://127.0.0.1:4320`（不带 `?token=`）：

1. 应出现登录卡；输入错误令牌 → 卡内"令牌不正确"；输入正确令牌 → 面板出数。
2. 勾选"记住我 30 天"登录 → DevTools Application/Cookies 中 `kb_tk` 的 Expires ≈ 30 天后。
3. 点"退出" → 回到登录卡，`/api/stats` 为 401。
4. 截图存 `.screenshots/login-card.png`（不提交）。

- [ ] **Step 6: 全量回归**

```powershell
$env:KB_SERVE_TOKEN=$null; $env:KB_SPIDER_HOME=$null
python -m pytest -q
```

Expected: 全部通过（新增用例计入，总数不少于本次改动前）。

- [ ] **Step 7: 提交**

```powershell
git add README.md USAGE.md
git commit -m "docs: 观测面板登录与令牌配置说明"
```

---

## 自查记录

- 规格 §4.1 → Task 1、Task 4；§4.2 → Task 2；§4.3 → Task 2；§4.4 → Task 3；§4.5 → Task 3（文案表）；§4.6 → Task 2（HttpOnly/常量时间）+ Task 5（文档边界）；§7 测试 → Task 1/2/4 的用例 + Task 3 语法守护 + Task 5 全量回归。
- 类型一致性：`resolve_token` 仅在 Task 1 定义、main 使用；`_same_secret`、`_COOKIE_ATTRS` 在 Task 2 内自洽；`showLogin(msg)` 在 Task 3 内三处调用一致。
- 无占位符；所有命令均为 PowerShell 5 可执行形式。
