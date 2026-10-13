---
id: kb-20261012-0067
title: regex `\d{n}` 位数与语义边界互补不互替（SSE-S8 首跑踩坑）
type: pitfall
domain:
- backend
tags:
- regex
- datetime
- validation
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-10'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/SSE与测试基建.md
---

# regex `\d{n}` 位数与语义边界互补不互替（SSE-S8 首跑踩坑）

## 背景 / 现象

**日期**：2026-09-09（夜间）
**分类**：正则表达式 / 日期时间格式契约
**影响文件**：`tests/test_sse_cross_repo_channel_e2e.py::test_ts_stricts_19char_format_and_boundary`
**严重度**：中（TDD 首跑 red 1 项，抽 `_ts_semantically_valid` 后留下可复用双验范式）

### 现象

SSE-S8 首跑：
```
AssertionError: ts='2026-09-09 12:00:60' 应 fail, got Match[0, 19]
```

初版 `_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")`，`fullmatch("2026-09-09 12:00:60")` 过——因 `\d{2}` 只担**位宽**，`60` 两位合法、9 == 10 语义上越界但 regex 不拒。

## 根因

### 根因

`\d{n}` 匹配 **digit count**（位数），不匹配 **numeric range**（语义范围）：
- `\d{4}` 匹 `0000-9999` 都过，不区分 year range
- `\d{2}` 匹 `00-99` 都过，但 `mm=13`（13 月）/ `hh=24`（24 时）/ `ss=60`（60 秒）语义越界
- **数字位宽合法 ≠ 语义合法**——两者互补不互替

## 解决方案

### 修复（**双验范式：regex + strptime**）

```python
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

def _ts_semantically_valid(ts: str) -> bool:
    """严格 19-char 位数（regex）+ 语义数值校验（strptime）互补。
    regex 只担位数契约，数字越界由 strptime 二次验证。"""
    if not _TS_RE.fullmatch(ts):
        return False
    try:
        datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False
```

配 case：
- **regex 应 pass 但 strptime 拒**：`"2026-09-09 12:00:60"`（ss=60）/ `"2026-09-09 24:00:00"`（hh=24）/ `"2026-13-09 00:00:00"`（mm=13）/ `"2026-09-32 00:00:00"`（dd=32）
- **regex 应 fail 但 strptime 会 pass**（位宽错误）：`"2026-9-9"`（短单位跳转）/ `"2026/09/09 12:00:00"`（分隔符错）/ `"2026-09-09T12:00:00"`（T 分隔）/ `"2026-09-09 120000"`（cut 分隔）
- **双 pass**：`"2026-09-09 12:00:00"`
- **双 fail**：`"2026-13-99 99:99:99"`

## 验证

原文实录首跑 red 断言 `ts='2026-09-09 12:00:60' 应 fail, got Match[0, 19]`（真实运行证据）；「修复」段给出双验范式（regex 位宽 + strptime 语义）与配套 case 清单。

## 适用边界与反例

### 什么时候会复活

- 任何 regex 位数锁但业务要"数字在合法范围内"的契约（时间戳/百分比/坐标值/HTTP 状态码区间）
- 任何 regex 分隔符锁但语义要对齐语义内容（IPv4 `1.2.3.999` legal 位宽 / illegal range）
- 混 word-boundary（`\b`）跟位宽 / range 校验里再叠 1 层 regex 但用**同一个** regex 想一份做完两件事

### 检测点 + 预防 checklist

写 TDD 边界 case 时：

1. **checklist-1**：regex 只担**什么维度**？位宽 / 分隔符 / 字面 / 集合？—— 别一件事 regex 想嫌语义
2. **checklist-2**：语义维度 claim 是否**能**被 regex 覆盖（时间段 OK，IP range 就 lock 不到）？
3. **checklist-3**：语义维度要怎么补？`strptime` / `int(x) bounds` / `in WHITELIST` / `try: parse → except`？

任一 checklist 2/3 答不上来 → **不要在 regex 里放大语义 claim**，拆层写两个 checks。

### 同款典型信号

- TDD 边界 case 首跑 red，但 case 值是"位宽正确但语义 wrong"（如 `13:xx` / `ss=60`）——补 strptime / 数值比较
- 一句 regex 对内嵌"业务合法性"的字段，发现 miss 了大量非法值
- 字段有 **non-negated range**（0-59 / 1-12 / 1-31）却 regex 匹 `\d+`

遇到以上信号 → **加 strptime / 数值比较**（不是 regex 里堆 `\d{1,2}(?:0[0-9]|[12][0-9])` 的复杂 pattern——后者更脆且难读）。

## 参考

- 源记录: `docs/known-pitfalls/backend/SSE与测试基建.md`
