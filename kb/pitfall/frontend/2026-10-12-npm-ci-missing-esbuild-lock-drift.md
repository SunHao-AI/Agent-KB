---
id: kb-20261012-02e4
title: 容器 `npm ci` 报 `Missing @esbuild/<platform> from lock file`：宿主 npm 11 重算了嵌套对等树却没落实可选平台包（2026-09-22
  web 61edc0f）
type: pitfall
domain:
- frontend
tags:
- npm
- lockfile
- docker
- esbuild
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-22'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 容器 `npm ci` 报 `Missing @esbuild/<platform> from lock file`：宿主 npm 11 重算了嵌套对等树却没落实可选平台包（2026-09-22 web 61edc0f）

## 背景 / 现象

> 面向：`flysee_video_web/frontend`（`Dockerfile.prod` 用 `node:20-alpine` + `npm ci`）。凡"本地能跑、容器 `npm ci` 炸"且报 **Missing ... from lock file** 的都按本条排查。

`dev.ps1 start -Build` 构建前端镜像失败：

```
#24 [frontend builder 4/7] RUN npm ci
npm error Missing: @esbuild/openbsd-x64@0.28.2 from lock file
npm error Missing: @esbuild/openharmony-arm64@0.28.2 from lock file
npm error Missing: @esbuild/sunos-x64@0.28.2 from lock file
...
npm error Run "npm help ci" for more info
```

本地 `npm run test` / `vite build` 全部正常，`package-lock.json` 顶部 `"lockfileVersion": 3` 也正常。

## 根因

（三层叠加）：

1. `package.json` 里 `vite: 6.4.3`（顶层锁定，esbuild `^0.25`）+ `vitest: ^4.1.10`。vitest 4 的对等依赖 `vite: ^6||^7||^8` 解析到了 **vite 8.2.0**，嵌套装在 `node_modules/vitest/node_modules/vite`（rolldown 时代版本），其对等依赖是 `esbuild: ^0.27.0 || ^0.28.0`。
2. 宿主 npm **11.19** 某次操作重算了这棵嵌套对等树，在 `node_modules/vitest/node_modules/vite` 节点写了 `peerDependencies.esbuild: ^0.27||^0.28`，但**没有落实**对应的 `node_modules/vitest/node_modules/@esbuild/*`（可选平台包）与 `esbuild@0.28.2` 条目——本地 node_modules 早已存在，幂等判断没补。
3. `npm ci` 是"按锁文件精确复现"：发现"声明要求 0.28 但树里没有落实条目"即整包拒绝。`node:20-alpine` 内置 npm **10.8.2** 同样拒绝。`npx/npm/pnpm exec` 都会先安装依赖，**绕不过**；而直接调用包二进制（`node_modules/.bin/vitest`）不触发检查——这就是"本地全绿、容器炸"的判定特征。

## 解决方案

（必须用与 Dockerfile **同版本**的 npm 重算，避免宿主 npm 11 的默认行为把顶层 `vite@6.4.3` 也"顺手升级"）：

```powershell
docker run --rm -v "d:/WorkPlace/Pycharm/flysee_video_web/frontend:/app" -w /app node:20-alpine `
  sh -c "npm install --package-lock-only --ignore-scripts"
```

结果：仅新增嵌套条目（vitest 作用域下 esbuild@0.28.2 + 26 个 @esbuild 平台包 + rollup/rolldown/postcss 等，+512 行），**顶层声明依赖一个没动**（diff 只 + 无 -）。

## 验证

（定位是谁要求 0.28.2）：

```powershell
Select-String -Path frontend\package-lock.json -Pattern '0\.28\.2'          # 顶层无 → 是 peer 声明不是树
Select-String -Path frontend\package-lock.json -Pattern '"node_modules/vite": \{' -Context 0,3  # 确认顶层 vite 版本
```

## 适用边界与反例

- 改 `package.json`（尤其动 vitest/vite 这类带宽对等范围的测试基建）后，提交 `package-lock.json` 前跑一次与 CI/镜像相同的 npm 大版本验证：`docker run --rm -v {PWD}:/app -w /app node:20-alpine sh -c "npm ci --ignore-scripts"`，比 push 后等 CI 快。
- `Missing: X from lock file` ≠ 包名拼错/registry 挂了，是**锁文件自身不一致**；`npm install` 在本地"看起来正常"不代表锁一致。
- 宿主 npm major 与镜像 npm major 不一致（11 vs 10）是这类漂移的高发背景；锁文件尽量由镜像侧 npm 生成。

修复后 `8b6c5f0b`（T5 清死依赖）在宿主 npm 重新生成 lock 时**又把同一棵嵌套 esbuild@0.28.2 子树整段洗掉**——证明只要"改 package.json 后没走镜像同款 npm 校验"这条纪律破一次，漂移必然复发（且"只删不增"同样触发）。本次按上文同款命令补回 +512 行纯新增，容器 `npm ci --dry-run` 输出 `added 135 packages` 后提交流水线。**新增判别捷径**：`git show <rev>:frontend/package-lock.json | Select-String 'node_modules/vitest/node_modules/esbuild'` 一查即知某提交 lock 是否含该条目，可快速二分"哪个提交洗掉了它"。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
