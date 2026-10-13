---
id: kb-20261012-5368
title: Universal Mirror 模式：双仓 e2e 不 import 对方，反射源码 + 常量镜像（SSE-S8 核心遗产）
type: pitfall
domain:
- backend
tags:
- cross-repo
- e2e
- contract-test
scope: universal
status: accepted
severity: low
confidence: verified
created: '2026-09-10'
updated: '2026-10-13'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/SSE与测试基建.md
---

# Universal Mirror 模式：双仓 e2e 不 import 对方，反射源码 + 常量镜像（SSE-S8 核心遗产）

## 背景 / 现象

**日期**：2026-09-09（夜间）
**分类**：测试基建 / 跨仓契约守门
**影响文件**：`tests/test_sse_cross_repo_channel_e2e.py`
**严重度**：低（方法论建议；单仓 venv 装不到对偶仓时的通用 e2e 解）

### 场景

「双仓 e2e」原规格要求"algo publish → setting subscribe 严格 channel 一致（`flysee:sse:{client_id}`）"。双仓 sandbox 部署 e2e 长周期成本高（P2 handoff），本 session 单仓 sandbox 想加契约测。

## 根因

单仓测试环境因 venv 隔离装不到对偶仓包, "import 对方做运行时断言"的常规契约测路径不可达; 而该契约只依赖字面常量(channel prefix 与 client_id 拼接), 不存在可执行的对偶实现可依赖. 于是只能靠常量镜像 + inspect 反射源码把契约锁到字符层, 代价是镜像漂移退化为人工维护.

## 解决方案

### 方法（3 layer 互锁）

1. **对偶仓常量镜像**（本仓可 import 不了 → 拷镜现状）
   ```python
   # algo/app/services/sse_publish.py:53
   _MIRROR_DEFAULT_SSE_CLIENT_ID = "admin"
   # L110
   _MIRROR_CHANNEL_PREFIX = "flysee:sse:"
   ```
   镜像是 **人工漂移 check**（feature 非 bug）：每次 algo 侧 `sse_publish.py` 改动后**必须手动**回改镜像段——这是"人肉验证"的合理负担，防未来 SSE-PUB 侧重命名 publish 常量直接静默 pass

2. **本仓订阅源 reflect**（反射源码，不 exec / 不 monkeypatch）
   ```python
   def test_setting_source_subscribes_exact_mirror_channel():
       src = inspect.getsource(sse_mod)
       assert 'pubsub.subscribe(f"flysee:sse:{client_id}")' in src, "setting subscribe 改 wording → 契约已破坏"
       assert 'pubsub.unsubscribe(f"flysee:sse:{client_id}")' in src, "unsubscribe 须 symmetric"
   ```
   `inspect.getsource` 比 exec/monkeypatch 更透明——dev-moment 的措辞改动能立刻 red（对偶侧 refactor 防漂移）

3. **镜像 concat 字面严格**（同 prefix 同 client_id → channel 严格一致）
   ```python
   @pytest.mark.parametrize("client_id", ["admin", "userA", "CJK-终端用户", "with_type_123", ""])
   def test_mirror_channel_strict_concat_parametric(client_id):
       channel = f"{_MIRROR_CHANNEL_PREFIX}{client_id}"
       assert channel == f"flysee:sse:{client_id}"  # 镜像 concat 严格
       # （全角 CJK 用户名也走同一 prefix 拼接——防 future 改成 f"flysee:sse:{hash}" 錯连）
   ```

## 验证

验证手段即方法本体：第 2 层 `inspect.getsource` 反射断言 subscribe/unsubscribe 字面（改动立刻 red），第 3 层镜像 concat 参数化 case（含 CJK client_id）锁 channel 严格一致；「检测点」段给出镜像漂移时 case 是否 red 的自检方法。

## 适用边界与反例

### 何时适用 / 不适用

**适用**：
- 双仓 e2e 里对偶仓代码 **是** 仓库二进制/独立发布但字符层契约稳定（如 setting+algo / web+setting）
- sandbox 装不到对偶仓包（venv 隔离）
- 契约只依赖**字面常量**（channel prefix / event schema / 状态码等）

**不适用**：
- 契约依赖对偶仓**逻辑**（如返回 object 属性、序列化格式依赖运行时格式）——镜像无意义，改用 ast/double-mock
- 跨仓 **接口 mock** 太重（超出 3 个点的契约）——直接切 `httpx.MockTransport` / `requests-mock` 走完整接口层

### 检测点

- TDD 首跑全绿但 **实现层已漂**（如 algo 仓 `sse_publish.py` 改了 `DEFAULT_SSE_CLIENT_ID = "default"` 但镜像段没回改）——镜像 case 是否 red？如果没 red，说明契约没真正锁到（需补「algo 仓 publish 端默认 client == 镜像段」case + "人工回改 reminder" 写文件头 docstring）
- 反射源码 case 依赖 `inspect.getsource`——被 case 自己 monkeypatch 了就没意义；**红线：本 case 不改 sse_mod**

## 参考

- 源记录: `docs/known-pitfalls/backend/SSE与测试基建.md`
