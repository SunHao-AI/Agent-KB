# 蜘蛛轨道缓动过渡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除回放中蜘蛛在首词到达/翻页/过滤等时刻的瞬移, 轨道参数(cx/cy/rx/ry)平滑缓动过渡。

**Architecture:** `livePose` 拆为 `orbitTarget`(参数) + `poseFromOrbit`(参数→位姿)两个纯函数; `LiveRenderer` 持有缓动后的 `orbit` 状态, 每帧向 `orbitTarget` 目标指数平滑, 蜘蛛画在缓动轨道上。后端与协议零改动。

**Tech Stack:** 原生 ESM(Canvas 2D), node:test 单测, 浏览器实测用 TRAE browseruse。

**Spec:** `d:\Workplace\Agent-KB\docs\superpowers\specs\2026-10-21-spider-orbit-easing-design.md`

## Global Constraints

- 仓库: `E:\Workplace\prompt-spider-ui`(改动只落此仓的 `app/` 与 `tests/`); 测试命令 `cd E:\Workplace\prompt-spider-ui; npm test`。
- `livePose(layout, time, reducedMotion, tight)` 对外签名与返回值 `{x,y,vx,vy}` 不变。
- 缓动参数: τ=0.35s; snap 条件: 首帧 / reducedMotion / dt≤0 或 dt>0.5s / hypot(Δcx,Δcy)>场景对角线×0.6。
- 注释用中文, 风格随现有代码(紧凑、单行)。
- 基线已知失败: `live-ui.test.mjs` 第 6 行布局列表断言缺 `wall`(上轮遗留), Task 1 顺带修复; 除此之外任何测试失败都视为本计划引入的回归。
- 提交信息用 conventional commits(中文描述), 提交范围只含本任务涉及文件。

---

### Task 1: 纯函数层 — orbitTarget / poseFromOrbit / easeOrbit

**Files:**
- Modify: `E:\Workplace\prompt-spider-ui\app\live-layout.js:42-51`(livePose 一带)
- Modify: `E:\Workplace\prompt-spider-ui\tests\live-ui.test.mjs`(第 3 行 import、第 6 行基线修复、文件末尾追加)
- Test: 同上一文件

**Interfaces:**
- Consumes: 现有 `livePose` 内联表达式(wall→tight/wallArea, 其他→场景比例)。
- Produces:
  - `orbitTarget(layout, tight=null) -> {cx, cy, rx, ry}`
  - `poseFromOrbit(orbit, time, omega, reducedMotion=false) -> {x, y, vx, vy}`(语义 = 现 livePose 主体)
  - `easeOrbit(current, target, dt, tau=0.35) -> {cx, cy, rx, ry}`(指数平滑, dt 秒)
  - `livePose(layout, time, reducedMotion=false, tight=null)` 行为不变(内部改走上面两个函数)

- [ ] **Step 1: 修复基线失败 + 写失败测试**

`tests/live-ui.test.mjs` 第 6 行改为(wall 与 landscape 同页尺寸):

```js
  assert.deepEqual(Object.values(LIVE_LAYOUTS).map(x => [x.width, x.height]), [[1080, 1350], [1600, 900], [1080, 1080], [1600, 900]]);
```

第 3 行 import 追加三个新函数名(此时运行会因导出不存在而失败):

```js
import { LIVE_LAYOUTS, livePose, eventPlacement, hitEvent, resolveCursor, parseSseFrames, orbitTarget, poseFromOrbit, easeOrbit } from '../app/live-layout.js';
```

文件末尾追加:

```js
test('poseFromOrbit(orbitTarget(...)) equals livePose (pure refactor)', () => {
  const wall = LIVE_LAYOUTS.wall, tight = { x: 300, y: 250, w: 420, h: 130 };
  for (const [layout, t] of [[wall, 0], [wall, 3.7], [LIVE_LAYOUTS.portrait, 9.2]]) {
    for (const tightArg of (layout === wall ? [tight, null] : [null])) {
      const omega = Math.PI * 2 / 16;
      assert.deepEqual(poseFromOrbit(orbitTarget(layout, tightArg), t, omega), livePose(layout, t, false, tightArg));
    }
  }
  assert.deepEqual(poseFromOrbit(orbitTarget(wall, tight), 5, 0, true), livePose(wall, 5, true, tight));
});

test('easeOrbit approaches target monotonically without overshoot', () => {
  const from = { cx: 700, cy: 400, rx: 300, ry: 250 }, to = { cx: 500, cy: 300, rx: 210, ry: 60 };
  let cur = from, prev = Infinity;
  for (let i = 0; i < 60; i++) {
    cur = easeOrbit(cur, to, 1 / 60);
    const d = Math.hypot(cur.cx - to.cx, cur.cy - to.cy);
    assert.ok(d < prev); prev = d;                       // 单调逼近
  }
  assert.ok(Math.hypot(cur.cx - to.cx, cur.cy - to.cy) < 1);  // 1s 后基本收敛
  const half = easeOrbit(from, to, 0.25);                     // k=1-e^(-0.25/0.35)≈0.51: 单帧不过跳
  assert.ok(Math.hypot(half.cx - from.cx, half.cy - from.cy) < 0.6 * Math.hypot(to.cx - from.cx, to.cy - from.cy));
  const frame = easeOrbit(from, to, 1 / 60);
  assert.ok(Math.hypot(frame.cx - from.cx, frame.cy - from.cy) < 0.1 * Math.hypot(to.cx - from.cx, to.cy - from.cy));
  assert.deepEqual(easeOrbit(from, to, 30), to);              // dt→∞ 精确落位
  const still = easeOrbit(to, to, 0.5);
  assert.deepEqual({ x: still.cx, y: still.cy }, { x: to.cx, y: to.cy }); // 目标不动则不动
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:\Workplace\prompt-spider-ui; npm test`
Expected: live-ui 两个新 test FAIL(`orbitTarget is not defined` / import SyntaxError), 其余原样(仅基线第 6 行修复后转绿)。

- [ ] **Step 3: 最小实现**

`app/live-layout.js` 将现有 `livePose`(42-51 行, 含注释)替换为:

```js
// 轨道参数(椭圆中心+半径): wall 对准词团实际 bbox(缺省回落 wallArea), 其余布局用场景比例。
// 从 livePose 抽出, 供渲染层缓动(参数连续变化 => 位置连续, 蜘蛛不再瞬移)。
export function orbitTarget(layout, tight=null) {
  const s=layout.scene;
  if(layout===LIVE_LAYOUTS.wall){const a=tight??wallArea(s);return {cx:a.x+a.w*.5,cy:a.y+a.h*.5,rx:a.w*.42,ry:Math.max(60,a.h*.42)};}
  return {cx:s.x+s.w*.39,cy:s.y+s.h*.50,rx:s.w*.075,ry:s.h*.33};
}
// Closed analytic orbit: position AND velocity join smoothly, at any elapsed time.
export function poseFromOrbit({cx,cy,rx,ry},time,omega,reducedMotion=false) {
  const angle=reducedMotion?1.3:time*omega;
  return {x:cx+Math.cos(angle)*rx,y:cy+Math.sin(angle)*ry,vx:-Math.sin(angle)*rx*omega,vy:Math.cos(angle)*ry*omega};
}
// 轨道参数帧率无关指数平滑: k=1-exp(-dt/τ)。目标突变时参数连续逼近, 观感为蜘蛛巡游过去而非跳过去。
export function easeOrbit(current,target,dt,tau=0.35) {
  const k=1-Math.exp(-Math.max(0,dt)/tau);
  const mix=(a,b)=>a+(b-a)*k;
  return {cx:mix(current.cx,target.cx),cy:mix(current.cy,target.cy),rx:mix(current.rx,target.rx),ry:mix(current.ry,target.ry)};
}
export function livePose(layout,time,reducedMotion=false,tight=null) {
  const omega=reducedMotion?0:Math.PI*2/16;
  return poseFromOrbit(orbitTarget(layout,tight),time,omega,reducedMotion);
}
```

注意等价性: 原 wall 分支 `rx=a.w*.42`、`ry=Math.max(60,a.h*.42)`; 非 wall `rx=s.w*.075, ry=s.h*.33`——逐项一致, reducedMotion 时 omega=0 且 angle=1.3 保持原值。

- [ ] **Step 4: 运行确认全绿**

Run: `cd E:\Workplace\prompt-spider-ui; npm test`
Expected: 全部 PASS(含原有 45 项; 基线修复后无 fail)。

- [ ] **Step 5: Commit**

```powershell
cd E:\Workplace\prompt-spider-ui
git add app/live-layout.js tests/live-ui.test.mjs
git commit -m "refactor(live): 抽出 orbitTarget/poseFromOrbit 并新增 easeOrbit 轨道缓动纯函数"
```

---

### Task 2: 渲染层接入缓动(LiveRenderer)

**Files:**
- Modify: `E:\Workplace\prompt-spider-ui\app\live-renderer.js`(import 行、constructor、`web()`、`spider()`)

**Interfaces:**
- Consumes: Task 1 的 `orbitTarget(layout,tight)`、`poseFromOrbit(orbit,time,omega,reducedMotion)`、`easeOrbit(current,target,dt,tau)`。
- Produces: `LiveRenderer.orbit`(缓动后的当前轨道参数, 测试钩子 `window.spiderLive.renderer` 已可读到)。

- [ ] **Step 1: 改 import 与 constructor**

第 1 行 import 追加 `orbitTarget, poseFromOrbit, easeOrbit`:

```js
import { LIVE_LAYOUTS, eventPlacement, hitEvent, routeTarget, livePose, orbitTarget, poseFromOrbit, easeOrbit, alpha, tightBox } from './live-layout.js';
```

constructor 末尾(`canvas.addEventListener(...)` 之后)加轨道缓动状态:

```js
    this.orbit=null;this.orbitTime=0;this.orbitPos=null;   // wall 轨道缓动状态(参数+上帧位置+上帧时刻)
```

- [ ] **Step 2: web() 内用缓动轨道取代直算**

`web()` 现为 `body=livePose(this.layout,time,reducedMotion,this.wallTight??null)`(第 56 行)。
改为(保留函数尾部 `this.spider(body,...)` 调用不变):

```js
    const body=this.easedPose(time,reducedMotion);
```

并在类中新增方法(spider() 之前):

```js
  // 蜘蛛位姿 = 沿"缓动后的轨道"取当前角度。目标轨道参数(词团 bbox/翻页/过滤)突变时参数指数逼近,
  // 位置保持连续; snap 场景(首帧/reducedMotion/后台恢复/大幅 seek)直接落位。
  easedPose(time,reducedMotion) {
    const s=this.layout.scene,target=orbitTarget(this.layout,this.wallTight??null);
    const now=(globalThis.performance?.now()||0)/1000,dt=now-this.orbitTime;this.orbitTime=now;
    const diag=Math.hypot(s.w,s.h)*.6;
    const snap=!this.orbit||reducedMotion||!(dt>0)||dt>0.5||Math.hypot(target.cx-this.orbit.cx,target.cy-this.orbit.cy)>diag;
    this.orbit=snap?target:easeOrbit(this.orbit,target,dt);
    this.orbitDt=snap?0:dt;   // 供腿速差分的合法帧间隔(0=本帧不采信差分)
    return poseFromOrbit(this.orbit,time,reducedMotion?0:Math.PI*2/16,reducedMotion);   // omega 与旧 livePose 一致(reducedMotion→0)
  }
```

- [ ] **Step 3: 腿速改用实测帧间差分**

`spider()`(第 75-81 行)中 `speed:Math.hypot(body.vx,body.vy)` 改为缓动后真实位移速率, 并把位置记账挪进 renderer。
constructor 状态已在 Step 1 加好, 修改 `spider()` 第一行循环前的 speed 计算:

```js
  spider(body,time,reducedMotion,theme){
    const c=this.ctx,now=(globalThis.performance?.now()||0)/1000;
    const speed=this.orbitPos&&now>this.orbitPos.t?Math.hypot(body.x-this.orbitPos.x,body.y-this.orbitPos.y)/(now-this.orbitPos.t)*16:Math.hypot(body.vx,body.vy);
    // 差分速率换算成与解析速度同量纲(ω 归一, 16=轨道周期秒数), 保证缓动期间腿摆动与真实位移同步。
    this.orbitPos={x:body.x,y:body.y,t:now};
    c.save();c.translate(body.x,body.y);c.rotate(Math.atan2(body.vx,-body.vy)||0);
    for(const side of [-1,1])for(let index=0;index<8;index++){const pose=legPose({time,reducedMotion,side,index,speed});...原样...}
    ...原样...
```

(仅替换 speed 来源与加记账, 腿部绘制逻辑不动; `Math.atan2(body.vx,-body.vy)` 朝向仍用解析速度——缓动期角度变化小, 朝向连续, 无需差分。)

- [ ] **Step 4: 回归 + 快速人工验证**

Run: `cd E:\Workplace\prompt-spider-ui; npm test` → 全绿(渲染层无单测, 以 Task 3 浏览器实测为准)。

- [ ] **Step 5: Commit**

```powershell
cd E:\Workplace\prompt-spider-ui
git add app/live-renderer.js
git commit -m "feat(live): 蜘蛛轨道参数指数缓动, 首词到达/翻页/过滤不再瞬移"
```

---

### Task 3: 浏览器实测 + 测试文档 §17

**Files:**
- Modify: `d:\Workplace\Agent-KB\docs\tests\2026-10-21-full-coverage-test.md`(追加 §17)

**Interfaces:**
- Consumes: Task 2 完成的 `window.spiderLive.renderer.orbit`(读缓动状态); Agent-KB 4321 serve(按 D1 宽正则清理后重启)。
- Produces: §17 实测记录(逐帧无突跳的证据)。

- [ ] **Step 1: 清理残留 serve 并重启(D1 教训)**

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'kb(\.exe"?)?\s+serve|kb\.cli\s+serve' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
cd d:\Workplace\Agent-KB; kb serve --repo .   # 后台运行(web_server, blocking=false)
```

探针: `Invoke-WebRequest http://127.0.0.1:4321/ ` 的 HTML 含 `openReplay`; `/api/health` 的 `spider_ready=true`。

- [ ] **Step 2: 打开回放并采样蜘蛛位置**

browseruse 打开 `http://127.0.0.1:4321/`,进入 `t-20261021-3219` 回放(点条目开浮层, seek 到 0.0s 播放)。
在 t≈0.3-0.8s 窗口用 evaluate 每 ~16ms 采样 `renderer.orbit` 与渲染位姿(或直接连续 evaluate `orbit.cx/cy`),
断言相邻采样位移 < 20px; 首词到达帧前后重点覆盖。

- [ ] **Step 3: 其余突跳场景**

- 词墙第 2 页↔第 1 页翻页: 采样 orbit 中心滑移连续(翻页瞬间目标变, 0.8s 内走完 90%);
- 路由过滤切换(如 all→code): 同上;
- 词墙↔列表开关: snap 或滑移均接受, 但不得出现半途回抽;
- 进度条从 0.5s 拖到 4s: 期望 snap(无长距离漂流)。

- [ ] **Step 4: 写入 §17 并截图留证**

`docs/tests/2026-10-21-full-coverage-test.md` 追加 "§17 蜘蛛轨道缓动过渡" 一节: 现象、根因一句话、
采样数据(最大相邻帧位移)、各场景结论、截图 `screenshot_uri` 存档路径。

- [ ] **Step 5: Commit(Agent-KB 仓)**

```powershell
cd d:\Workplace\Agent-KB
git add docs/tests/2026-10-21-full-coverage-test.md docs/superpowers/specs/2026-10-21-spider-orbit-easing-design.md
git commit -m "docs(tests): §17 蜘蛛轨道缓动实测 + spec 步进阈值修正"
```

(若用户未授权提交此仓文档, 跳过 commit 仅保留文件并说明。)

---

## Self-Review 结论

- Spec 覆盖: §2.1→Task 1; §2.2→Task 2; §3 边界全部落进 Task 2 snap 条件与腿速; §4.1→Task 1 测试; §4.2→Task 3。无缺口。
- 阈值勘误: spec 的"dt=0.5s 步进<60%"数学上不成立(k≈76%), 已改为 dt=0.25s/1/60s 两点断言并同步 spec。
- 接口一致: `orbitTarget/poseFromOrbit/easeOrbit` 三处引用签名一致; `renderer.orbit` 为 Task 3 采样钩子。
- 已知取舍: 腿速差分换算 `*16`(周期归一)属观感参数, 实测若腿摆过快可在 Task 3 微调系数。
