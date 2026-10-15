# 工作地图 — 商用发布 v1 × Agent-KB 产品化 (2026-10-14)

> 定位: 自己驱动执行的工作地图。每项带入口锚点/验收标准/依赖, 开工时直接引用本文件对应编号。
> 框架: 双轨并行 (方案 A) — Track A 商用发布里程碑驱动, Track B Agent-KB 产品化独立轨, 技术债显式挂账 (§6)。
> 前提事实: 生产基本无真实客户 (演示/自用) → 灰度保护降格, 节奏压快。
> 布局前提: 五仓同级克隆于 `d:\WorkPlace\Pycharm` (flysee-video-setting / flysee_video_web / flysee_video_algorithm / flysee_media_server / Agent-KB); 跨仓锚点均带仓名前缀。

## 0. 使用说明

- **勾选框** = 待办; `[挂账]` = 明确不做, 只保清单 (§6)。
- **依赖符号**: `←` 表示前置任务编号。
- **状态权威源**: 本文件 + 各任务入口文档; 与本文冲突以任务入口的 spec/plan 为准。
- 锚点路径: 无仓名前缀者相对本仓 (Agent-KB); 带 `flysee-*` 前缀者相对同级业务仓。
- 粒度约定: Track A 大块任务 (以天计), Track B 全部 ≤半天粒度 — 保证双轨切换成本可控。

## 1. 现状快照 (2026-10-14, 已核实)

- 四仓主干 (均已 push): flysee `fdfd4bc` / web `0594b560` / algo `1878762` / media `1866200`; 本仓 `b11c7f7` (GitHub+gitee 双远端, submodule 指针全仓一致)。
- 授权体系代码面基本齐: RS256 v2 密钥环 / 三态机 / .zluf 离线包 / .zapk 加密交付 / 审计账本 GENESIS / 反破解 T-24 T-26 P2 已实施 / 权威门 setting 侧一期已合 (enforce 缺省 off) / **台账 entitlement-ledger 27 提交已合 master** (含 stale_after 加固)。
- 回归基线: setting 913 passed / web 729 / algo 669 / 本仓 115。
- 通用库 195 条 (stack 174 + universal 21), 全部 accepted; P2 终审 229 条队列已清零。
- 硬缺口: **四仓零 CI**、coverage 无门禁、`.mcp.json` 硬编码绝对路径、116 条占位 warning、`review_by` 零启用、全库 100% pitfall 单类。

## 2. Track A — 商用发布 v1 (主轴)

任务序即推荐执行序。里程碑见 §5。

- [ ] **A1 台账 DDL 执行 + S2-S7 上线收口** ← (无)
  - ✅ 2026-10-14 S1-S3 全部落库: DDL 四件套核实 (表×2 + export_releases.entitlement_ids + 菜单 9 节点) + 回填差异归零 (dry-run created=0/skipped=3, 10-12 已回填) + 全客户对账 SQL 实跑 — 14/16 号客户台账↔包完全一致; 1/FS016 missing=新台账行未重新导出 (预期不阻断); 13/FS017 extra=A3 已废弃行的包侧历史快照 (人工审放行)。**无 expiry_mismatch**。
  - 剩余: S4-S7 (切读源/web G-1/G-2 observe→enforce 全量) 与 E2E 全链复验按 spec 序推进。
  - ✅ 2026-10-14 Agent 侧交付完成: 一页纸执行包 `flysee-video-setting/docs/ops/2026-10-14-entitlement-ddl-execution-pack.md` (备份→S1 DDL→S3 回填+全客户 JSON_TABLE 对账 SQL 已在 mysql:8.0.46 实测四场景→回滚→失败模式速查); 两个 migration 文件尾注已按仓内规范补 `ROLLBACK:` 注释段。
  - 入口: `flysee-video-setting/docker/init/migrations/2026-10-12-entitlements.preview.sql`、`2026-10-12-entitlement-menu-perms.sql`、`flysee-video-setting/backend/scripts/entitlements_backfill.py` (幂等回填)、台账 spec §12 上线序 (`flysee-video-setting/docs/superpowers/specs/2026-10-12-algorithm-entitlement-ledger-design.md`)。
  - Agent 交付"一页纸执行包": DDL + 回滚 SQL + 对账脚本, 人工操作压到 10 分钟 (DDL 禁止 Agent 代执行)。
  - 无真实客户 → S3 双轨期缩短, 对账一次过即可; G-2 灰度开关 (`suite_gate_enabled`) 直接全量开。
  - 验收: 回填对账 100% 对齐; E2E 全链绿 — 台账下单 → 导出 → web 导入 → 建单闸门 G-1 → 引擎闸门 G-2 → 过期拒绝 (E_LICENSE_006)。
- [x] **A2 权威门 observe → enforce 切换** ← A1 ✅ 2026-10-14 三场景 E2E 全绿, 生产已切 enforce
  - 实测记录 (TTL 压缩 600s 加速, 收尾已还原 7200): **A 在线续期** — 同步 renewed+att_cached、断言 exp 随续期刷新; 篡改 JWS payload rev_epoch+99 → 探针 403 E_LICENSE_007 (读时重验签即废, attestation_present 翻 False) → 再同步自愈恢复。 **B 离线容差** — stop setting 后 fails 1→2→3 即 degraded 翻转; 等断言过期后探针仍放行 (401 非 007) = **气隙+enforce 组合零误伤坐实** (降级判定优先于断言过期); 恢复后 renewed、fails 复位 0。 **C 吊销时效** — revoke(epoch 16) 落审计 + web sync renewed=False + setting 落 renew_denied; TTL 窗口内探针明示残余放行; 断言过期后探针 **403 E_LICENSE_007 = 吊销实效上界 = 断言 TTL** (非 token 剩余寿命); restore→同步即自愈。
  - 发布态验证: web `.env` `LICENSE_ONLINE_AUTHORITY=enforce`、setting TTL 还原 7200、最终 license-state `state=valid mode=enforce fails=0 degraded=False`。
  - 执行包: `flysee-video-setting/docs/ops/2026-10-14-enforce-e2e-pack.md` (本轮按其执行, 结果即上条实测记录)。
  - 验收: enforce 模式三场景 E2E 绿 — 在线续期 / 离线容差 / 吊销时效。**硬门禁: 三绿才发**。 — **三绿达成**。
- [x] **A3 算法库发布前清理: FS017-019 等 17 个 stale 模型处置** ← (无, 可与 A1 并行) ✅ 2026-10-14 完成
  - 处置记录: handoff §二.2 已改写为决策+落库凭证 (`flysee-video-setting/docs/handoff/2026-10-14-authorization-security-closeout-handoff.md`)。要点: 残留密文当日已物理清 (18:48 抽检全绿), `algorithm_library` FS017/018/019 软删 is_del=1 (备份+回滚语句在 handoff), 台账/审计行不动; 顺带发现 FS020/021 保留在售、目录补录挂 §6。
  - 入口: handoff 记录 (`flysee-video-setting/docs/handoff/`)。
  - 验收: 每个模型有去留结论并落库。 — 17 个残留模型全部收敛为「废弃」结论并落库。
- [ ] **A4 发布工件包** ← A1 A2 A3
  - 入口: `flysee-video-setting/docs/ops/deployment-checklist.md` (扩台账步骤)、`flysee-video-setting/scripts/secure/` + `docs/deploy/secure-delivery-deployment.md` (web/setting secure 镜像重建, 现缺 r3/r4)、flysee 仓根 `tmp_totp.txt` / `_new_totp_enc.txt` / `_final_bench.mjs` / `.it-tmp/` 清理、打 tag `v1.0`。
  - 验收: 按 checklist 从空机到可演示一次通过。
- [ ] **A5 backlog 尾巴收口** ← (无, 穿插)
  - 入口: `flysee-video-setting/docs/backlog/2026-10-12-授权模块后续任务.md` — T2 气隙回执计数不清零 (方案 A/B 已列)、T4 algo 测试隔离、T5 Minor 备忘。
  - 验收: 三项关闭或有理由挂账入 §6。
- [x] **A6 最小工程门禁** ← (无, 建议最先做) ✅ 2026-10-14 完成 + 首验闭环
  - 落地: 母本 `scripts/pre-push-gate.sh` + 安装器 `scripts/install-gate.ps1` (本仓), 五仓全装 (web 仓原 LFS pre-push 保留为 `pre-push.chain` 由 launcher 串联); 增量 lint 硬门禁只查 push 范围 .py 且规则收窄 F+E9 (全仓存量 451/274/97 条挂账 §6, 全仓硬门禁会堵死 push), pytest 全量硬门禁, coverage 报告不设阈值, `PREPUSH_SKIP=1` 应急跳过。
  - 首验 (五仓 push 全绿): 门禁连拦三案 — ① Agent-KB test_cli F401; ② web 生产 `.env=enforce` 泄漏测试面 (180+ 用例 403, 修 conftest 钉 off, `ffbee7ff`); ③ 用户 S1 信封 WIP 与旧契约测试冲突 → 由此暴露设计缺陷并修正 (下条)。web 全量 729→732 passed / coverage 87%。
  - 设计缺陷修正 (`16e083d`): lint 判定对象改为**被推 ref 内容** (`git show tip:file` 喂 ruff stdin), 工作区 WIP 不再污染; pytest/npm test 就地跑前校验测试面 (py/config) 工作区↔待推 tip 一致, 不一致即拦并给三条处置 (提交/stash/SKIP), 杜绝假绿。零风险 plumbing 合成 commit 三场景自检通过。
  - 入口: 四仓 `pyproject.toml` + git hooks。
  - 验收: 带失败测试无法 push。 ✅ 宿主机五仓 push 实测 (拦截×3 + 放行×5)。

## 3. Track B — Agent-KB 对外推广/多团队 (独立轨, 可与 A 交错)

- [ ] **B1 接入体验先行** ← (无, 可即刻开工)
  - `kb init`: 为接入仓生成 `.mcp.json` (去绝对路径, 现四仓硬编码 `d:/WorkPlace/...python.exe`) + 引导 venv 装配。
  - `kb doctor`: 自检命令, 收编全部已知失败模式 — venv 缺失 / submodule 悬空 / index 漂移 / `--repo-name` 大小写 / `.gitmodules` url 不可达。**并吸收 A6 门禁已实现的自检清单** (母本 `scripts/pre-push-gate.sh` §0 + 执行包 §6: venv 缺 pytest / 缺 ruff / pytest-cov 降级 / 容器 env 三件套), doctor 直接复用同一口径。
  - ~~修 `index --check` 目录名大小写环境问题~~ ✅ 2026-10-14: repo 字段统一小写规范名 (cli/layers/mcp_server 三处 `.lower()` + 新回归测试 `test_index_repo_name_case_normalized`), 本地 `Agent-KB` 下 `index --check` rc=1→rc=0, 全仓 118 passed。
  - 对外 quickstart + 拿一个真实新仓 dogfood; README 同步 review/set-scope/export 三命令 (现缺)。
  - 验收: 新仓三步接入 clone → `kb init` → `kb doctor` 全绿。
- [ ] **B2 内容质量门** ← (无, 天然穿插活, 每批 ~20 条)
  - 116 条占位回填: 验证段 69 / 适用边界段 40 / 背景 4 / 解决方案 3 (fixwave-A 官方口径)。web/algo 原 known-pitfalls 约 30 条有证据可搬, 其余如实降级 probable。
  - 复用 P2 已验证流程: 子代理提案表 → 批次认定 → 落地 (账本 `.superpowers/sdd/2026-10-14-p2-scope-review/`)。
  - ~~完成前 `kb lint` 加 `--strict` 挡增量~~ ✅ 2026-10-14: `kb lint --strict` + baseline 机制落地 (`.kb-lint-baseline` 116 条存量豁免; 新 warning 即拦、已修复条目提示收缩、`--update-baseline` 固化), pre-commit kb-lint 已切 `--strict`; 2 条行为测试, 全仓 118 passed。占位分布核实 = 验证 69 / 适用边界与反例 40 / 解决方案 3 / 背景 4 (含 root-cause 文案变体), 与 fixwave-A 官方口径一致。**剩余**: 116 条回填本体 (每批 ~20 条, 复用 P2 流程)。
  - 验收: 占位 warning 清零 + strict 门禁上线。
- [ ] **B3 知识生命周期启用** ← B2
  - `review_by` 按 confidence 分级设到期 (verified 180d / probable 90d); `kb stat --due-review` 进周期例程 (代码链已就绪, 数据零启用)。
  - 非 pitfall 七类至少启用 decision + howto 两类试点, 破 195 条单类单薄感。
  - 验收: due-review 队列非空且每周期有人清; 两类新 type 各有真实条目。
- [ ] **B4 多团队协作套件** ← **触发器: 第一个真实外部用户出现** (设触发器不设日历)
  - MCP HTTP 传输 + token 鉴权 (多团队远端使用打破 P0 spec §13 "同信任域"前提, 届时重开该决策)。
  - 多团队 proposed 双阶审批流设计 (先 spec 后码, 走 SDD)。
  - I-3 token 查重 deadlock (P1 唯一显式挂账 P2 项, progress.md)。
  - cross-repo related 设计 (related 边全库 = 0, 功能虚设; Task 13 note)。
  - 验收: 各子项独立 spec 先行过审。
- [ ] **B5 继续挂起 (不排期)**: 飞书/Notion 镜像 (无真实协作需求信号)、RAG (触发条件 = 命中率不足, 未触发)、PyPI 发布 (bootstrap 脚本够用)。

## 4. 双轨汇合点

1. A6 的失败模式清单 → 直接演化为 B1 `kb doctor` 检查项 (一次劳动两处受益)。
2. 商用发布 tag 后, flysee 四仓即 B1 quickstart 的 dogfood 对象与推广演示素材。
3. Track A 上线过程产生的新坑按沉淀协议进项目库 → P2 流程上提通用库 → 对外推广时"库是活的"的证明。

## 5. 里程碑时间轴

| 里程碑 | 内容 | 前置 |
| --- | --- | --- |
| M1 | A6 最小门禁 + A1 台账 DDL/E2E 全绿 | 用户执行 DDL |
| M2 | **商用发布 v1** (A2 enforce + A3 + A4, 打 tag) | M1 |
| M3 | B1 接入体验包 + B2 占位清零 | 可与 M1/M2 并行穿插 |
| M4 | B3 生命周期启用 + 对外首秀 (一个外部仓 dogfood) | M3 |
| 触发器 | B4 多团队套件 (含 MCP HTTP) | 第一个真实外部用户 |

## 6. 显式挂账 (本轮不做, 发布后再议)

| 项 | 证据锚点 | 挂账理由 |
| --- | --- | --- |
| 上帝文件拆分 | flysee `mysql_impl.py` 1452 / `export_service.py` 1247 / `model_service.py` 1057 行 | 无新需求压身时不动刀 |
| 跨仓 6 文件逐字节重复抽包 (flysee-shared) | 三仓分析 §2.1 | 发布前改跨仓依赖结构风险>收益 |
| 前端死代码清理 (~42%) | 三仓分析 §3.1 | 不影响发布 |
| A1 去共享库 / A2 Redis Stream 架构项 | `flysee-video-setting/docs/analysis/2026-10-10-三仓系统设计缺陷与优化分析.md` | 中期架构项 |
| C2 真实凭证落盘 `.env.prod.bak` 整改 / C7 审计链外部锚定 / C10 密钥自动轮换 | 三仓分析 §4.2; 反破解 P3 receipt 解耦 (`flysee-video-setting/docs/security/anti-crack-hardening-roadmap-20261013.md` L97-102, 原文即"可长期挂起") | 安全中期项 |
| 100+ 跨仓 pending 表 (AL-P0-2~5 / AL-P1-* / TASK-BOOT / B-17~B-21) | `flysee-video-setting/docs/superpowers/2026-09-09-cross-repo-pending-tasks.md` | 逐项复核时再激活 |
| CI 完整方案 (GitHub 镜像 + Actions) | 四仓零 CI 现状 | A6 本地 hook 先顶 |
| 全仓 ruff 存量欠账 (setting 451 / web 274 / algo 97, 过半可 `--fix`) | 2026-10-14 A6 实测 `ruff check` 全仓计数 | A6 增量门禁只挡新错 (F+E9); 存量清欠择日一次 `--fix` + 人工复核 |
| spec/plan checkbox 回填 (setting 累计 753 处) | `flysee-video-setting/docs/uncompleted-work-2026-09-04.md` | 文档债 |
| FS020/FS021 商品目录补录 (catalog_items 无行, 库保留在售) | A3 盘点 2026-10-14: `algorithm_library` is_del=0 但从未导出、无台账 | 发布面因无台账天然导不出, 无风险; 台账运营发布后再议 |

## 7. 关键风险与对策

| 风险 | 对策 |
| --- | --- |
| 台账 DDL 是唯一"不可 Agent 代执行"卡点 | A1 一页纸执行包 (DDL+回滚+对账), 人工操作 ≤10 分钟 |
| 双轨并行注意力分散 | B 轨全部 ≤半天粒度, A 轨大块; 穿插优先级: B2 批次 > B1 小项 |
| stale_after × 权威门 × 台账三机制组合语义只推演未实战 | A2 三场景 E2E 为发布硬门禁, 不过不发 |
| 无客户环境 → 测试环境即生产, 误操作无缓冲 | 操作前备份目标表 (既有 DDL 规范), A1 执行包含回滚 |
