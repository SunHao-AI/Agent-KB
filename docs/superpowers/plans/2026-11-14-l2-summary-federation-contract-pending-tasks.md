# 交付档案 — L2 摘要质量优化与联邦 L2 记录契约（计划已闭环）

> 状态: **CLOSED**（2026-11-14）
> 计划: `docs/superpowers/plans/2026-11-14-l2-summary-federation-contract.md`
> 设计: `docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md`
> 台账: `.superpowers/sdd/2026-11-14-l2-summary-federation-contract/progress.md`（git-ignored）
> 终审报告: 同目录 `final-review-report.md`（git-ignored）
>
> 本文件原为跨会话待办交接档案，计划闭环后转为交付记录，保留区间清单与遗留裁决。

## 交付区间

`3db155e`（基线）→ `ad9a43c`（已推送 origin/master）

| 提交 | 内容 |
| --- | --- |
| `ee40826` → `d969b9c` | Task 1-9：schema/entry/index/lint/stat/gate/cli-mcp/templates/契约条目，各任务评审 Approved |
| `c9d8fa7` | 终审 F1+F2：lint 缺失按值判（解除模板空串占位对守护线的屏蔽）+ spec §3.3 口径回写 |
| `25fff17` | 终审 F3：`kb new` 未传 `--summary` 时 stderr 提示补写结论句 |
| `6fda806` | 终审 F4：契约条目补注 `origin` 判定过渡态（经 gate 合规通道，revision 留痕） |
| `f6a2463` | 终审 F5：门禁探针按 UTF-8 解码子进程输出，中文 Windows 不再假红 |
| `d1cc8b8` | set-scope `kb-20261114-b226` → stack（scope 终审落地，红线 #2 由用户授权后代执行） |
| `0d0edca` | 重建 docs 库索引补 `origin`/`uri`，消 `index --check` 存量 stale |
| `ad9a43c` | 沉淀两条实测坑（`kb-20261114-a0bb` / `kb-20261114-c102`） |

推送两次均过 `pre-push-gate` 全部门禁段（lint 增量 + kb 双库 strict + index --check + 全量 pytest），
coverage 87%。

## 终审结论

**Needs fixes → 修复波 F1-F5 全部落地 → scoped re-review Approved。**

核心发现是跨任务接缝（详见 `kb-20261114-a0bb`）：T4 把"缺 summary"实现成键不存在才告警，
T8 又按 spec 给 8 个模板加 `summary: ""` 占位，两任务各自评审均通过，合起来守护线对模板
产物永久失效。这类缺陷单任务评审不可见，是整分支评审的独有价值。

## 遗留与裁决（不阻塞）

- **独立评审缺口**：终审与修复波由控制器本体完成——该会话 Agent 通道被 `disallowedTools`
  禁用（`general-purpose` / `Explore` / 回落默认类型三次均报 disabled）。若要求独立复核，
  需在允许 subagent 的会话重跑。
- **守护线 = 硬门禁**：`lint` 侧 summary 规则恒为 warning，但 pre-push 跑的是
  `kb lint --strict` 且 `.kb-lint-baseline` 为空 → **2026-11-15 起**缺 summary 的新条目
  会直接拦下推送（实测 normal=0 / strict=1）。这与 F3 加的 CLI 提示构成"提示 + 强制"闭环，
  与 spec §3.3 "不挂门禁"的措辞存在口径张力。未擅自改 `SUMMARY_REQUIRED_SINCE` 或 baseline；
  若次日不想即刻强制，需在 11-15 前调整常量或门禁策略。
- **`kb-20261114-c102` 待人工上提**：已 `promote` 建议（`promote-to:stack` +
  `needs-scope-review`），scope 仍 project。跨项目通用（任何 Windows + subprocess 场景），
  建议人工 `kb set-scope kb-20261114-c102 stack --repo docs` 落地。
- **deferred-minor 7 项**：见 `progress.md` 与终审报告第四节（spec/条目双文本漂移、
  AGENTS.md `--repo .` 语境、coverage 两口径、anyOf 报错笼统、旧行缺 origin 无守卫测试、
  纯空白 summary、docstring 措辞）。均不阻塞。
- **测试"全绿"须注明环境**：F5 修复后默认 GBK 控制台亦 517 passed；此前"517 passed"
  仅在 UTF-8 会话成立。
