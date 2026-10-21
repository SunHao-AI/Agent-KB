---
id: kb-20261021-c3d3
title: browseruse press_key 空格的 keydown.key 为空串致键盘逻辑误判失效
type: pitfall
domain:
- testing
tags:
- browser-automation
- keyboard-events
- auto-reviewed
scope: project
status: accepted
confidence: verified
created: '2026-10-21'
updated: '2026-10-21'
severity: medium
verified_by: agent
verification:
  evidence: 'docs/tests/2026-10-21-full-coverage-test.md §21: 插桩捕获 key='''' + 合成 KeyboardEvent(key=''
    '') 回放即开, 双向对照实测'
  reviewed_at: '2026-10-21'
---

# browseruse press_key 空格的 keydown.key 为空串致键盘逻辑误判失效

## 背景 / 现象
用 browseruse `browser_press_key({key:' '})` 验证"检索流条目聚焦后按空格开回放"的键盘逻辑,
连续两次页面无反应, 一度误判为产品缺陷(Enter 正常、空格失效)。

## 根因
在页面捕获阶段插桩 `addEventListener('keydown', e=>..., true)` 取证: 事件确实到达目标容器且
`e.target` 正确, 但 **`e.key` 是空字符串 `''`** 而非规范值 `' '`。产品代码 `e.key===' '` 判断
不匹配属正常行为——是自动化驱动发键时 key 值缺失, 与页面逻辑无关。

## 解决方案
涉及空格/特殊键的键盘逻辑验证, 不信自动化键值, 改为页内合成标准事件直接验证产品逻辑:

```js
el.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', bubbles: true, cancelable: true}));
```

排查顺序: 先插桩确认"事件是否到达 + key/target 实际值", 再决定是否怀疑产品代码。

## 验证
2026-10-21 实测: `press_key(' ')` 插桩捕获 `key=""`, 回放未开; 同条目派发合成
`KeyboardEvent(key:' ')` 后回放浮层 `.open` 立即为 true(同一 keydown 处理器)。
测试记录: docs/tests/2026-10-21-full-coverage-test.md §21。

## 适用边界与反例
- 适用: 任何通过 CDP/自动化驱动按键并断言产品键盘交互的测试(空格、修饰键组合同样先插桩看实际 key 值)。
- 反例: Enter/Escape 等常用键实测键值正常, 无需绕行; 合成事件 `isTrusted=false`,
  若被测逻辑依赖 trusted 事件(少见)则该方法只能作旁证。

## 参考
- MDN KeyboardEvent.key: 空格规范值为 `" "`(单个空格字符)。
- 同仓方法论: §18 `.open` 类断言、§20 iframe 媒体查询实测。
