---
id: kb-20261014-9043
title: submodule 指针 bump 到主仓未 push 的 commit 致异机不可达; --remote 跟错分支拉回旧 head
type: pitfall
domain:
- devops
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-14'
updated: '2026-10-14'
review_by: '2027-04-12'
severity: medium
source:
  project: agent-kb
---

# submodule 指针 bump 到主仓未 push 的 commit 致异机不可达; --remote 跟错分支拉回旧 head

## 背景 / 现象

多仓以 submodule 挂同一知识库仓时，两类连环故障：① 父仓把 submodule 指针 bump 到主仓新提交后，异机 `git submodule update --init` 报 `Fetched in submodule path '.agent-kb' did not contain <sha>`——主仓当时没有可推的远端（或 push 滞后于 bump），指针在 submodule 声明 url 指向的远端上不可达；② 用 `submodule update --remote` 想让指针跟主干，`.gitmodules` 里 branch 配错/缺省时静默跟默认分支，把指针拉回旧 head（flysee 四仓 P1 期间实测踩中）。

## 根因

submodule url（含相对形式 `../X`，按父仓 origin 解析）声明了异机取件的唯一来源；bump 只改父仓 gitlink 记录，不校验该 sha 在 url 目标仓是否可达。`--remote` 则相反：不看父仓 gitlink 只看远端分支 tip，branch 配置错时方向性拉错。两个方向的失效都不在本地报错，只在异机/CI 暴露。

## 解决方案

固化 bump 顺序为三步：主仓先 push（指针所在 commit 先可达）→ 父仓 `git -C .agent-kb fetch <主仓本地路径或远端> master` 后 checkout 目标 sha → 父仓提交 bump。主仓暂无远端的过渡期，bump 提交信息里写明待补 push；禁止用 `--remote` 做常规 bump，只在确认 branch 配置后显式使用。

## 验证

2026-10-14 P2 落地实测：gitee 旧名仓 404、主仓无远端期间指针悬空被识别；主仓配好 GitHub/gitee 双 push 并推平后（`5785457` 双远端可见），按上述三步 bump 四仓，异机可达性恢复。

## 适用边界与反例

纯本地单机布局（submodule url 指向本地路径）不受影响；若 url 直接写本地绝对路径则异机本就不可用，属另一种反模式。

## 参考

交接文档 `flysee-video-setting/docs/handoff/2026-10-14-p1-closeout-handoff.md` §2.5 候选；P2 落地会话 submodule bump 操作记录。
