---
id: kb-20261012-0496
title: Python 数值 `in` + bool/int 子类陷阱：whitelist 判型必加 `type is int`（SSE-S8 首跑踩坑）
type: pitfall
domain:
- backend
tags:
- python
- whitelist
- type-check
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-10'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/SSE与测试基建.md
---

# Python 数值 `in` + bool/int 子类陷阱：whitelist 判型必加 `type is int`（SSE-S8 首跑踩坑）

## 背景 / 现象

**日期**：2026-09-09（夜间）
**分类**：Python 语言陷阱 / TDD whitelist 判型
**影响文件**：`tests/test_sse_cross_repo_channel_e2e.py::test_close_reason_whitelist_exact_0123`
**严重度**：中（TDD 首跑 red，修复后留下可复用判型范式；池子里若同类 case 蔓延就不止 30s）

### 现象

SSE-S8 首跑 `test_close_reason_whitelist_exact_0123` 红：
```
AssertionError: close_reason=3.0 应不在 whitelist [0,1,2,3], got 3.0 in (0,1,2,3)=True
```

初版判型 `for bad in (3.0, "3", None, True, False, -1, 4): assert bad not in (0, 1, 2, 3)` 预期全部 fail 白名单——但 `3.0 in (0,1,2,3)` 是 **True**（Python 数值 `==` 判定），`False in (0,1,2,3)` 也是 True（bool 是 int 子类），`True` 同为 True。

## 根因

### 根因

Python `in` 判定语义是**逐项 `==` 比较**，跨 int/float 走 `==` 数值比较：

```python
>>> 3.0 in (0, 1, 2, 3)
True
>>> 3.5 in (0, 1, 2, 3)
False
>>> True in (0, 1, 2, 3)
True     # bool isinstance int，True == 1
>>> False in (0, 1, 2, 3)
True     # False == 0
>>> "3" in (0, 1, 2, 3)
False    # str != int
```

## 解决方案

### 修复（**双保险判型范式**）

```python
whitelist = (0, 1, 2, 3)

def is_close_reason_legit(v) -> bool:
    # 层 1：严格判型（bool 是 int 子类，须先隔离）
    if isinstance(v, bool):
        return False
    if type(v) is not int:
        return False
    # 层 2：whitelist 白名单
    return v in whitelist

# TDD 里针对每个 bad case 的判据也要写双保险：
for bad in (-1, 4, 100, 3.0, "0", True, False):
    e = _mirror_build_event("a" * 32, "stopped", close_reason=bad)
    is_int = type(e["close_reason"]) is int           # 严格判型
    in_wl = e["close_reason"] in whitelist            # 白名单
    if isinstance(bad, bool):
        assert is_int is False, f"bool 不是 int 类型（隔离分支）"
    else:
        assert (not is_int) or (not in_wl), f"{bad!r} 应 fail type 判或 whitelist 判"
```

核心判据 `(not is_int) or (not in_wl)`：
- 非 int 类型 → fail 第一条（`not is_int` True）
- 是 int 但不在 whitelist → fail 第二条（`not in_wl` True）
- bool 是 int 但 0/1 ∈ whitelist → 走**专属分支** `assert is_int is False`（因为 `True` 型走不到第二条——否则会静默 pass）

## 验证

原文实录首跑 red 断言 `close_reason=3.0 应不在 whitelist [0,1,2,3], got 3.0 in (0,1,2,3)=True`，并附交互式验证 `>>> 3.0 in (0, 1, 2, 3) True` / `>>> True in (0, 1, 2, 3) True`（真实运行证据）；「修复」段给出双保险判型范式（`type is int` + whitelist）。

## 适用边界与反例

**逻辑推论**：白名单 `in` 判定能拒绝的只有**纯类型错误**（str/None/dict/list…），**不能**拒绝"数值等价的另一类型"（float 3.0 == int 3 / bool True == int 1 / bool False == int 0）。

### 什么时候会复发

- 任何 whitelist 判型，case 集合含 float/int 相邻值（3.0 / 1.0 / 0.0）
- 任何 whitelist 判型，case 集合含 `True/False`（bool 是 int 子类，0/1 常同 whitelist 里就有）
- 用 `isinstance(x, int)` 判型但**忘排 bool**——`isinstance(True, int)` 是 True

### 检测点 + 预防 checklist

白名单 case 写作 TDD 时：

1. **checklist-1**：case 集合含**数值等价跨类型**吗？float `3.0` / bool `True`（==1）/ bool `False`（==0）？
2. **checklist-2**：`in` 判定的 fallback 是"数值相等但类型错误"还是"类型不同"？前者需 `type is X` 严格判型
3. **checklist-3**：`isinstance(x, int)` 后是否**显式排除 bool**（`type is int` / `not isinstance(x, bool)`）？

任一 checklist 命中 → 写判型前置 `type is int` / `not isinstance(bad, bool)`。

### 同款典型信号

- TDD whitelist case 首跑绿但"意外 pass"某些 case（值不同但数值相同的 float 也 in whitelist）
- `False in (0, 1)` 或 `True in (0, 1)`——bool 假扮 int 打穿 whitelist
- 想拒 `3.0` 却发现 `3 in whitelist and 3.0 in whitelist` 都 True

遇到以上信号 → **加 `type is int`**（不是 `isinstance`，后者 `bool is int=True`）。

## 参考

- 源记录: `docs/known-pitfalls/backend/SSE与测试基建.md`
