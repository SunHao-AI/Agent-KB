# 蜘蛛轨道缓动过渡 — 设计文档

> 日期: 2026-10-21 · 仓: prompt-spider-ui(前端) · 关联: `docs/tests/2026-10-21-pending-tasks.md`(新增项 F)
> 现象: 回放中蜘蛛在首词到达瞬间从场景区域中心瞬移到词团中心(图1 t=0.00 → 图2 t=0.51), 突兀无过渡;
> 翻页/过滤/事件增多导致词团 bbox 变化时同样瞬移。

## 1. 根因

蜘蛛位姿由解析轨道 `livePose(layout, time, reducedMotion, tight)`(`app/live-layout.js`)给出:
椭圆中心/半径对准**当前可见词团的实际 bbox**(`tightBox`, §16 修复引入)。
首词到达前 `tight=null` → 回落 `wallArea`(场景中部大方块)→ 蜘蛛绕区域中心转;
首词到达后 `tight` 变为单词 bbox → 椭圆中心/半径**瞬时**改变 → 蜘蛛 teleport。
`angle=time*omega` 对 time 连续, 不连续的是**轨道参数本身**(cx/cy/rx/ry)。

## 2. 方案(已选定: 轨道参数缓动)

保持 `livePose` 签名与返回值不变, 在渲染层对轨道参数做帧率无关的指数平滑。
所有突跳场景(首词、bbox 变化、翻页、过滤)都归结为同一组目标参数变化, 一处机制全覆盖。

### 2.1 live-layout.js(纯函数层)

- 从 `livePose` 内提取 `orbitTarget(layout, tight)` → `{cx, cy, rx, ry}`(与原表达式逐项相等);
- `livePose(...)` 改为 `poseFromOrbit(orbitTarget(layout, tight), time, omega)` — 行为不变, 现有测试原样通过;
- 新增 `easeOrbit(current, target, dt, tau=0.35)`: 逐分量 `current + (target-current)*k`,
  `k = 1 - exp(-dt/tau)`(帧率无关; τ=0.35s ≈ 0.8s 走完 90%)。

### 2.2 live-renderer.js(状态与缓动)

`LiveRenderer` 新增实例状态: `orbit`(当前生效参数)、`orbitTime`(上帧 performance.now)、
`orbitPos`(上帧实际绘制位置, 供腿速差分)。`web()` 内:

1. 目标 = `orbitTarget(layout, tight)`;
2. **snap 条件**(任一命中直接 `orbit=目标`, 不缓动):
   - 首帧无 `orbit`(图1 静置展示态零变化);
   - `reducedMotion`(该模式本就静止姿态);
   - `dt<=0` 或 `dt>0.5s`(页签后台恢复, 防补动画);
   - `hypot(Δcx,Δcy) > 场景对角线×0.6`(手动 seek 大幅跳, 瞬移符合预期;
     布局切换 wall↔landscape 基准不同, 由本条自然兜住);
3. 否则 `orbit = easeOrbit(orbit, 目标, dt)`;
4. 蜘蛛位姿 = `poseFromOrbit(orbit, time, omega)` — 角度仍用 `time*omega`,
   蜘蛛沿缓动后椭圆继续转、中心滑向新位置, 位置 C0 连续;
5. `legPose` 的 `speed` 改为实测帧间差分 `hypot(pos-orbitPos)/dt`, 缓动期间腿速与真实位移一致; 绘制后更新 `orbitPos`。

**不改**: `web()` 中 24 条 mesh 蛛丝与 route 贝塞尔(只依赖 `routeTarget`, 不随 tight 变);
`live.js`(renderer 自持 performance.now 求 dt); 后端与 spider_export(无协议变化)。

## 3. 边界与明确不做

- dt 用 `performance.now()` 差值而非回放时间: seek/倍速/暂停不影响缓动节奏;
  暂停时 angle 冻结, 缓动走完蜘蛛即静止, 与现状一致。
- 不为翻页/过滤编写脚本化巡游路径(缓动自动产生的滑移已足够, YAGNI)。
- 不做 crossfade 淡入淡出(只是把"跳"换成"闪", 已否决)。

## 4. 测试与验收

### 4.1 单测(`tests/live-ui.test.mjs` 追加, `npm test`)

1. `easeOrbit` 单调逼近目标; `dt→∞` 收敛到目标;
2. dt=0.25s/τ=0.35 时单帧步进 < 60% 距离、dt=1/60s 时 < 10%(防跳; dt>0.5s 本就走 snap, 不进缓动);
3. `poseFromOrbit(orbitTarget(layout,tight),t,omega)` 与旧路径 `livePose(layout,t,false,tight)` 深相等(重构无回归)。

### 4.2 浏览器实测(4321 serve, 先按 D1 宽正则清残留进程再重启; 探针确认 served HTML)

- 回放 `t-20261021-3219`: t≈0.4s 首词到达前后逐帧取蜘蛛位置, 无 >20px/帧 突跳;
- 翻页、路由过滤、词墙↔列表开关各确认一次平滑滑移;
- 拖动进度条大幅 seek 确认 snap(不漂流);
- 结果补入 `docs/tests/2026-10-21-full-coverage-test.md` §17。

## 5. 与遗留清单的关系

本项为 `2026-10-21-pending-tasks.md` 之外的新增项(记为 F: 蜘蛛过渡)。
范围约定: 本 spec 只覆盖 F; 完成后按 A(提交/沉淀, 提交前另行确认)→B(B1/B2 实测)→
C(逐条向用户拍板)顺序继续推进清单。
