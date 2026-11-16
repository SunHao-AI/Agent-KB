---
id: kb-20261107-3916
title: '非 UTF-8 字节拖垮 trace 全链路: append-only 账本读侧必须替换解码'
type: pitfall
domain:
- tooling
tags:
- trace
- jsonl
- utf-8
- 解码
- 编码
- errors-replace
- append-only
- 账本
- 容错
- unicode-decode-error
- 非utf-8
- 观测数据
- trace-report
- 炸全链路
scope: project
status: draft
confidence: speculative
created: '2026-11-07'
updated: '2026-11-07'
severity: medium
---

# 非 UTF-8 字节拖垮 trace 全链路: append-only 账本读侧必须替换解码

## 背景 / 现象

`kb trace report --format md` 整条命令直接失败，栈顶是：

```
kb error: 'utf-8' codec can't decode byte 0xac in position 17158: invalid start byte
```

同期 `kb serve` 的 feed / callers / KPI 端点、`kb stat` 的观测口径也一并失效——不是
"少一条 trace"，而是**所有读 trace 的功能全挂**。单实例复现：`traces/2026-11-07.jsonl`
共 19883 字节，偏移 17157 处（第 24 行行首，紧跟在上一行 CRLF 之后）是一个孤立的
`0xAC` 字节，其后接着 `", "` 这样的 JSON 片段。

## 根因

两层叠加：

1. **写入侧落进本地代码页残片**：某次 trace 事件经 Windows 管道/重定向写出时混入 GBK
   字节（`0xAC` 是 GBK 某汉字的第二字节，首字节已丢失），形成**不完整的多字节序列**。
   `kb trace append` 自身用 `encoding="utf-8"` 打开文件，不会产生这种内容；残片来自
   外层 shell 的字节级重排。
2. **读侧整文件严格解码**：`src/kb/trace.py` 的 `_parse_file()` 用
   `f.read_text(encoding="utf-8")` 一次性解码整个 jsonl。`UnicodeDecodeError` 发生在
   **拿到任何一行之前**，所以此后所有容错分支（bad line 跳过、非对象事件跳过、脏类型
   归一）全部没有机会执行——已有的行级防御被解码这一层整体绕过。

关键认知：该账本是 **append-only 且每日定时提交进 git**（`kb-20261102-3c9c`），
坏字节一旦落盘、提交、推送，就**永久留在历史里**。所以"把那一行改对"在流程上是禁止的
（篡改历史事件 = 伪造观测数据），只能让读侧容错。

## 解决方案

只改读侧，不动历史数据（`src/kb/trace.py`）：

```python
lines = [ln for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()
         if ln.strip()]
```

`errors="replace"` 把非法字节变成 U+FFFD，包含它的行随即在 `json.loads` 处失败，落回
**既有**的 bad line 分支（跳过该行 + 记 warn），其余事件照常统计。这与 `index.py` /
`bootstrap.py` 里读 `index.jsonl` / `.gitmodules` 的既有写法一致，是同一套"外部/历史
产物不可信"的口径。同时补回归用例 `test_read_survives_non_utf8_bytes`（写入合法 meta +
一条事件后再追加一行含 `0xAC` 的字节序列，断言事件仍全数返回且 warns 含 bad line）。

## 验证

- 修复前：`kb trace report --format md` 退出码 1，直接抛 UnicodeDecodeError。
- 修复后：同一命令正常输出（示例：待消化 29 / 上榜 30 · 消化率 3%，高频词表完整）。
- 回归用例 + 全量：`414 passed`（含新增用例），两个远端各跑一轮 pre-push 门禁均 PASS。
- 真数据侧未改动：`traces/2026-11-07.jsonl` 坏字节原样保留，仅被跳过一行。

## 适用边界与反例

- 适用于**只读派生的观测/日志账本**：坏一行只损失一条事件，不该让整条链路不可用。
- 不适用于**权威字节流**（许可证容器、签名载荷、模型权重）：那里替换字节等于静默损坏
  数据，必须硬失败。
- 反例：发现坏字节就"修文件"——append-only 账本禁止改写历史；修正应该落在**写入侧**
  （统一 `encoding="utf-8"`，不让 shell 管道字节参与拼装），而不是回改账本。
- 若坏字节落在 JSON 结构字符上，该行会被整行跳过：这是可接受的损失，warn 已留痕，
  不要为了"救回这一行"在解码层做启发式猜测。

## 参考

- 修复点：`src/kb/trace.py` `_parse_file()`（读账本处）
- 回归用例：`tests/test_trace.py::test_read_survives_non_utf8_bytes`
- append-only 红线：`kb-20261102-3c9c`（读侧剔噪、不改写账本）
- 同类编码坑：`kb-20261012-367e`（PowerShell 管道编码截断）、
  `kb-20261012-24c3`（PS1 BOM/ANSI 解码）
- 提交：`dffae98 fix(trace): 非 UTF-8 字节不再拖垮 trace report, 补每日 traces 提交脚本`
