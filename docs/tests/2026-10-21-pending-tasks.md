# 2026-10-21 会话遗留任务清单

> 来源: 全覆盖测试与七轮交互改造会话(测试记录见 `docs/tests/2026-10-21-full-coverage-test.md` §1-§16)。
> 本清单供新对话逐项处理; 每项含描述、上下文、涉及文件与验收方式。
> 已完成项不在此列(URL 状态 §12、播放坞→整页→浮层演进、词墙布局与轨道修复、
> 时间轴 stagger、分页/定宽/可读标题、TOP10、上海时区时间等均已落地并实测)。

## A. 交付完整性(优先处理, 防止工作丢失)

### A1. 两仓改动全部未提交
- **状态更新(2026-10-21 新会话)**: prompt-spider-ui 已全部提交(基线 781bad5 + 缓动
  b1a0898/0a06636/4b756b5, 见 `.superpowers/sdd/2026-10-21-spider-orbit-easing/progress.md`);
  **Agent-KB 侧功能改动仍未提交**(下表所列 src/kb、web/index.html、tests、docs/kb 生成物等)。
- **Agent-KB** (`D:\Workplace\Agent-KB`): 修改 `src/kb/{cli,serve,spider_export,stats}.py`、
  `src/kb/web/index.html`、`tests/{test_spider_export,test_stats_serve}.py`、
  `docs/kb/INDEX.md`、`docs/kb/index.jsonl`; 未跟踪 `docs/tests/`(测试文档+本清单)、
  `docs/kb/pitfall/` 新条目(3 条沉淀)、`preview.gif`(用户提供的示例动图, 是否入库需确认)。
- **注意**: 提交前跑 `kb index --check --repo .` 确认生成物无漂移; `traces/` 由定时任务
  自动提交, 勿混入功能提交(AGENTS.md 红线)。提交需用户明确要求。

### A2. 知识沉淀差一条(门控名额下轮可用) — ✅ 已完成(2026-10-21)
- 已沉淀 `kb-20261021-3471`(docs/kb/pitfall/frontend/2026-10-21-bbox.md):
  "动画轨道几何须对准内容实际 bbox 且目标参数突变须缓动", 自审 accepted/verified,
  evidence=测试文档 §16+§17 逐帧实测; `kb index` 已重建、`--check` 无漂移。

## B. 待验证项(代码已实现, 未逐条实测)

### B1. 浮层"就地换 trace"未单独实测 — ✅ 已实测(2026-10-21, 提交 5e3727f)
- 键盘路径(Enter/Space→openFeed)断言全通: 标题/trace id/src session 就地换、进度归零、
  iframe 整文档重载无旧会话残留; 详见测试文档 §16 补充段。
- **新发现缺陷(未修)**: 浮层遮罩 `fixed inset:0` 挡住 feed 条目, **鼠标点击路径实测不可达**
  (与代码注释"点别的条目=就地换 src"意图矛盾), 仅键盘可达。修法待定: 浮层改非全屏遮罩,
  或条目侧提供"在上层浮层中打开"入口——需产品拍板(并入 C 类)。

### B2. 降级路径(桥不就绪→SVG 弹层)在浮层改造后未复测 — ✅ 已实测(2026-10-21, 提交 5e3727f)
- 4322 独立 serve 构造 `spider_ready:false`: 点条目开 SVG 弹层(非蜘蛛浮层)、命中行人类可读
  标题、Esc 关闭均通过; 详见测试文档 §16 补充段。

## C. UX 优化建议 — ✅ 全部完成(2026-10-21, 提交 9775750/1eeaeae, 实测见 task-C-report)

| # | 位置 | 问题 | 建议 | 结果 |
|---|------|------|------|------|
| C1 | 时间窗口 | "7天"无具体日期范围, 口径需脑算 | 窗口按钮 tooltip 显示 `since≈YYYY-MM-DD`(前端已有 sinceDate() 可复用) | ✅ winTitle 复用 sinceDate, render 内全量刷新 |
| C2 | 零命中榜 | "追因→"仅 12px 小按钮, 可点性差 | 零命中整行可点(与条目标题同行响应) | ✅ 整行可点+键盘可达(Enter/空格, 按钮焦点时不双触发) |
| C3 | 检索流 | 过滤框无键盘快捷键; 切视图瞬间 feed 清空无骨架 | `/` 聚焦过滤框; loadFeed 期间 2-3 行骨架条 | ✅ `/` 聚焦(输入区不劫持); 骨架条含 401/异常清理(feedFail) |
| C4 | 热门榜 | 标题 CSS 截断后悬停 title 只有 id | title 改"完整标题 · id"(feed 已做, 榜单未同步) | ✅ 口径已对齐 |
| C5 | 检索流 aria-label | 条目仍写"回放蜘蛛动画: xxx", 与新交互文案(浮层回放)不一致 | 改为"回放蜘蛛: xxx"或"打开回放: xxx" | ✅ 改"打开回放: xxx" |
| C6 | 回放浮层 | 遮罩 `fixed inset:0` 挡 feed 鼠标入口(B1 新发现) | 浮层停靠不遮检索流, 鼠标就地换 trace | ✅ `#rp` pointer-events 穿透+面板 auto, 宽屏停靠零重叠; 窄屏 rp-center 回退; 原"点遮罩关闭"取消(✕+Esc) |

## D. 环境/运维注意(非缺陷, 新会话开工前读)

### D1. 残留 serve 进程(已五次踩坑, 最高优先环境陷阱)
- 4321 现运行本会话最后启动的 serve(新代码, 可直接体验); 重启前必须用宽正则清干净:
  `Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'kb(\.exe"?)?\s+serve|kb\.cli\s+serve' }`
  (窄正则漏杀 `python -m kb.cli serve` 模块形态→新进程绑不上端口→服务旧 HTML)。
- 重启后先探针: served HTML 含 `openReplay`、`/api/health` 的 `spider_ready`, 再走查
  (serve 启动时一次性读 HTML, 改前端必须重启)。

### D2. 蜘蛛桥(node)子进程
- 桥由 serve 懒启动(如 55707 端口), serve 被杀后桥进程可能短留; 强清:
  `Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'prompt-spider-ui' -and $_.Name -match 'node' }`。

### D3. 两仓版本耦合
- `spider_export` 导出 `layout:"wall"` 依赖克隆仓 `lib/config.js` 白名单含 `wall`
  (本会话已加、同批); 若克隆仓被回滚/re-clone, 导入会被 `normalizeConfig` 拒收——
  升级需两仓同步(代码注释已标注)。

### D4. 测试数据陷阱
- PowerShell `ConvertTo-Json` 发中文 body 会转码成 `?????`(traces 里已有 `?????1..41`
  脏数据, 属测试遗留, 可清理 `$env:TEMP\kb-sim\traces`); 造数用浏览器内 fetch 或 Python。
- browseruse: 页面 `window.open` 的新标签不在 `browser_tabs` 列表; evaluate 里
  `\\d` 双反斜杠会被吃; 截图取 `screenshot_uri` 后用 Read 读图。

## E. 明确不做/已关闭(避免重复讨论)

- 参考演示底部三张图(confidence 曲线/words 矩阵/coverage)复刻: 需 trace 中不存在的
  数据, 只能造假, 已否决。
- 新标签整页回放: 被浮层方案取代(⤢ 仍保留整页出口)。
- brainstorm 原型服务器(41777): 已停(0 监听), 无需处理。
