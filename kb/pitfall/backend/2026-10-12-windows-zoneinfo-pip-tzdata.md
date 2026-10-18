---
id: kb-20261012-2d63
title: zoneinfo 在 Windows 宿主机必须 pip 装 tzdata（Linux 容器无需关心）
type: pitfall
domain:
- backend
tags:
- zoneinfo
- tzdata
- windows
- pep615
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/时区与容器.md
---

# zoneinfo 在 Windows 宿主机必须 pip 装 tzdata（Linux 容器无需关心）

## 背景 / 现象

> 面向：workspace 中 py 侧（`flysee-video-setting` / `flysee_video_algorithm`）依赖 `zoneinfo.ZoneInfo(...)` 解析 IANA 时区的开发机。2026-09-04 Task 7 TDD 实锤。

**现象**：Windows 宿主机 `.venv` 跑 `from zoneinfo import ZoneInfo; ZoneInfo('Asia/Shanghai')`，**正常 Linux 开发习惯一行直接 `ZoneInfoNotFoundError: 'No time zone found with key Asia/Shanghai'`**；紧邻的 `ModuleNotFoundError: No module named 'tzdata'` 才暴露真相：CPython Windows build 不暴露系统时区表，**唯一落地路径**是 `importlib.resources.files('tzdata')` 读 pip 包的 `zoneinfo` 字典文件。Linux 容器（slim / alpine / debian / rhel base）系统都自带 `/usr/share/zoneinfo`，所以同一行代码在 docker 里永远绿、在 Windows `.venv` 里永远红，**且无任何警告**。

## 根因

**根因**（CPython 源码机制）：
- `zoneinfo.ZoneInfo` 加载顺序：`_LOADERS` 两个候选——① `TZPATH`（Linux/macOS 系统路径 `/usr/share/zoneinfo`；Windows 默认 `[]`）、② `importlib.resources.files('tzdata')`（pip 包 zoneinfo 字典）。
- **结论**：Windows host 的 `ZoneInfo(任意 IANA 名)` 必失败，**必须** pip 装 `tzdata` 包；**无任何** Windows 系统配置（环境变量 / 注册表 / tz 服务）能让 CPython 跳过这个包。

## 解决方案

**解决**（本次 2026-09-04 主依赖方案）：

两仓 `pyproject.toml` `[project] dependencies` 段加 `tzdata`（**不是** `[dependency-groups].dev`）：

```toml
[project]
dependencies = [
    # ... 其它 deps
    # tzdata：zoneinfo.ZoneInfo("Asia/Shanghai") 在 Windows CPython 不暴露系统时区表，
    # 需显式装；Linux 容器内系统自带 /usr/share/zoneinfo，装上为零代价。
    "tzdata>=2024.1",
]
```

## 验证

原文「验证」段(本次已实测): 两仓 uv sync 后 `import tzdata` 输出 2026.3; `ZoneInfo('Asia/Shanghai')` 正常返回; `pytest tests/test_startup_timezone.py -v` 3 例 PASSED。

**验证**（本次已实测）：
```powershell
> cd d:\WorkPlace\Pycharm\flysee-video-setting ; uv sync ; .venv\Scripts\python -c "import tzdata; print('tzdata', tzdata.__version__ or 'ok')"
tzdata 2026.3
> cd d:\WorkPlace\Pycharm\flysee_video_algorithm ; uv sync ; .venv\Scripts\python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Shanghai'))"
Asia/Shanghai
> # Windows host .venv 跑 zoneinfo 测试（Task 7 的 TDD 自检）
> .venv\Scripts\python -m pytest tests/test_startup_timezone.py -v
PASSED  test_default_is_shanghai
PASSED  test_env_override
PASSED  test_now_after_setzoneinfo
```

## 适用边界与反例

- **Linux / macOS**：`TZPATH` 命中系统字典，loader 1 成功，永远走不到 loader 2。
- **Windows**：CPython Windows build 把 `TZPATH = []` 写死（PEP 615 明确：Windows 系统时区与 IANA 名命名空间无法稳定对应，故**不提供**系统时区表）。loader 1 跳过 → `files('tzdata')` → pip 包不存在 → `ModuleNotFoundError` → 包装为 `ZoneInfoNotFoundError`。
**为什么是主依赖**（不是 dev-only）：
- **dev-only 走不通**：dev-only 写入 `uv.lock` 但**不写入** `requirements.txt`（`uv export --no-dev ` 默认跳过）——Linux 生产容器未来若因某库通过 `import tzdata` 兜底，会因容器 image 漏装而 `ImportError`。**主依赖 = Windows host + Linux 容器全可用**。
- **Linux 容器代价 ≈ 0**：几秒钟下载，系统 zoneinfo 本来能用，pip tzdata 只参与 import 链的「后备」分支永远不被命中。
- **AGENTS.md 已声明决策**：说明早期 spec §4 约束被主动偏离 + 偏离原因，避免后人重新检阅 spec 时陷入「为什么不按旧约束做」的困惑。

**预防 / workspace 规范**：
- **仓内 grep `from zoneinfo import ZoneInfo` 引入点**：每一个出现（除测试外）的仓**必须**在 `pyproject.toml [project].dependencies` 里写 `tzdata>=2024.1` + 顶部注释说明（避免后人以为是「为了测试才装」）。
- **CI 侧**：workspace 若引入 CI，Windows 测试矩阵的容器/VM 必须 `uv sync`，否则任何 `ZoneInfo` 用法在 CI 也翻红——和 host 同根因。
- **Linux 容器不重复 `pip install tzdata`**：别在任何 Dockerfile 里 `pip install tzdata`（会引入几 MB 双份 data，毫无增量收益）。py 侧主依赖声明已够用。

## 参考

- 源记录: `docs/known-pitfalls/backend/时区与容器.md`
