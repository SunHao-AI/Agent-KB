---
id: kb-20261114-c102
title: 'subprocess text=True 不指定 encoding: 中文 Windows 按 GBK 解码 UTF-8 子进程输出, 断言伪装成
  TypeError'
type: pitfall
domain:
- testing
tags:
- auto-reviewed
- promote-to:stack
- needs-scope-review
- promoted
scope: project
status: accepted
confidence: verified
created: '2026-11-14'
updated: '2026-11-14'
severity: high
summary: 测试用 text=True 捕获子进程输出而不指定 encoding 时, 解码随控制台码页走; 中文 Windows 的 GBK 撞上 UTF-8
  字节会让读线程抛 UnicodeDecodeError 使 stderr 变 None, 断言报成 TypeError 而非真红, 修法是在捕获点写死 encoding=utf-8
  加 errors=replace
review_by: '2027-11-14'
verified_by: agent
verification:
  evidence: '本机实测三段式: (1) 默认 GBK 控制台 pytest tests/test_gate_base_anchor.py → 2 failed/4
    passed, 报错 TypeError: argument of type ''NoneType'' is not iterable, 伴随 _readerthread
    UnicodeDecodeError(''gbk'' codec can''t decode byte 0xab); (2) PYTHONUTF8=1 同文件
    → 6 passed, 证明解码口径是唯一变量; (3) 在捕获点加 encoding=utf-8 errors=replace 后, 默认 GBK 控制台
    → 6 passed 且全量 517 passed, pre-push-gate 实跑 PASS 并完成推送 aed3911..0d0edca'
  reviewed_at: '2026-11-14'
---

# subprocess text=True 不指定 encoding: 中文 Windows 按 GBK 解码 UTF-8 子进程输出, 断言伪装成 TypeError

## 背景 / 现象

`tests/test_gate_base_anchor.py` 两条用例在中文 Windows 上恒红，但报错形态与断言内容无关：

```
assert "退化为全树" in err, err
E   TypeError: argument of type 'NoneType' is not iterable
```

同一套测试在 UTF-8 会话（`PYTHONUTF8=1`）下 6/6 全绿。这类"换个终端就换个结论"的假红最耗人：
它既不像环境差异（报错是 `TypeError` 不是断言失败），也不像代码缺陷（被测脚本行为完全正常）。

真实影响被放大的地方在 CI/门禁：`scripts/pre-push-gate.sh` 就地跑 `pytest -q` 且**不设**
`PYTHONUTF8`，于是任何推送都被这两条拦下，唯一绕行手段是 `PREPUSH_SKIP=1` 跳过整个门禁——
为了一个测试自身的问题放弃全部门禁，代价完全不成比例。

## 根因

三层叠加，缺一不炸：

1. `subprocess.run(..., capture_output=True, text=True)` **不指定 `encoding`** 时，
   解码口径取 `locale.getpreferredencoding(False)`，中文 Windows 是 **GBK(cp936)**；
2. 被测 shell 脚本打印的是**中文 WARN，UTF-8 字节**；GBK 解到非法序列时不是替换字符，
   而是在 `subprocess._readerthread` 里 `buffer.append(fh.read())` 直接抛
   `UnicodeDecodeError`；
3. 该异常发生在**读线程**而非主线程，pytest 只把它降级成 `PytestUnhandledThreadExceptionWarning`，
   主线程看到的 `r.stderr` 是 **`None`**——于是 `in` 运算报 `TypeError`，
   真断言根本没执行到。

即：**解码崩溃伪装成"断言写错了"**。同一机制在 `ps1 无 BOM 被按 ANSI 读`
（kb-20261012-24c3）里也出现过，但那是"读文件"路径，本条是"读子进程管道"路径，修法不同。

## 解决方案

在捕获点显式声明解码口径，不要让测试跟随控制台码页：

```python
r = subprocess.run(
    [sh, str(GATE)], input=ref_lines, capture_output=True, text=True,
    encoding="utf-8", errors="replace",   # 子进程输出是 UTF-8 字节
    cwd=str(repo), env=env,
)
```

- `encoding` 对齐**被捕获方的实际字节口径**（这里是脚本自身的 UTF-8 输出），不是运行机器的码页；
- `errors="replace"` 兜住第三方输出里混入的非 UTF-8 字节，避免换个 locale 又炸一次；
- 只在需要断言文本的捕获点加，纯二进制/只判 `returncode` 的调用不必动。

## 验证

- 修复前（默认 GBK 控制台）：`2 failed, 515 passed`，两条失败均为 `TypeError: ... NoneType`；
- 修复后（同一默认 GBK 控制台，不加任何环境变量的调用方式）：`tests/test_gate_base_anchor.py`
  **6 passed**，全量 **517 passed**；
- `pre-push-gate.sh` 实跑 PASS 并完成推送（`aed3911..0d0edca`）；
- 归属取证：引入这两条用例的 `60f4f36` 是当时基线 `3db155e` 的祖先，本次功能区间内
  对这两个文件 **0 改动**——属存量测试可移植性欠账，不是被测代码回归。

## 适用边界与反例

- **成立**：被测对象输出含非 ASCII，且测试要断言其文本内容；宿主是 Windows 且未强制 UTF-8 模式。
- **不成立**：Linux/macOS 默认 UTF-8，不触发；`capture_output` 未开启（继承终端）不触发；
  被捕获方本身就按码页输出（如某些 Windows 原生 CLI）时，写 `encoding="utf-8"` 反而会引入新错，
  此时应显式指定对方的口径。
- **同类隐患**：只跑 `PYTHONUTF8=1` 取得的"全绿"结论**不可迁移**到门禁环境。任何"本地全绿但
  CI 红"的差异，先比对两边的 `sys.stdout.encoding`，再怀疑代码。
- 用 `errors="replace"` 会让"字符数断言"失去意义（替换符计入长度）；这类断言应改用字节数或正则。

## 参考

- 修复提交: 本仓 `fix(tests): 门禁探针按 UTF-8 解码子进程输出`(终审 F5)
- 姊妹条目: `kb-20261012-24c3`(PowerShell 5.1 读无 BOM `.ps1` 按 ANSI 解码)——同一码页根因、不同触发路径
- CPython `subprocess.py::_readerthread`（解码异常在子线程被吞的位置）
