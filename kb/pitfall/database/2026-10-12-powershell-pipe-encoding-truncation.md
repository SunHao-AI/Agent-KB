---
id: kb-20261012-367e
title: PowerShell 管道 `docker exec -i mysql` 把 SQL 中的中文算作 clause 名截断
type: pitfall
domain:
- database
tags:
- mysql
- powershell
- encoding
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
related:
- kb-20261012-961c
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/编码与字符集.md
---

# PowerShell 管道 `docker exec -i mysql` 把 SQL 中的中文算作 clause 名截断

## 背景 / 现象

用 `Get-Content <seed>.sql -Raw -Encoding UTF8 | docker exec -i ... mysql ...` 执行 seed SQL, 前端首页正常但后端 `/auth/profile` 返回 `可查看菜单[0项]`, 库内 `sys_menu` 已写入 65 行但 `name` 列全是乱码("Management","System","Dashboard"…), `sys_role` 一个都灌不进去(中断后第 15 行报 `Duplicate entry '?????' for key 'sys_role.uk_role_name'`)。

## 根因

PowerShell 默认对 stdin 用系统 code page 编码(中文环境 cp936)。`get-content -raw -encoding utf8` 拿到的是正确字符串, 但 `|` 转渡给 native 进程 `docker exec -i` 时, PS 用 OutputEncoding(默认 ASCII)+ 当前控制台 code page 二次编码; 其中中文字面量被吞掉, 导致 SQL 中 `'中文名','备 注 列'` 这种"字符串字面量紧邻反引号列名"的 token 被截断成不完整标识符。

## 解决方案

绕过方案(按优先级):

1. 首选: 用 Python 脚本(`subprocess.run(["docker","exec","-i",...],input=file.read_bytes(),...)`)直接从文件字节传给 stdin, 跳过 PS 编码层;
2. 把文件拷进容器: `docker cp <file> flysee-video-setting-mysql:/tmp/x.sql` 后 `docker exec ... mysql < /tmp/x.sql`(容器内是 bash 的 stdin, 零翻译);
3. 若只能在 PS 用管道: 先 `$OutputEncoding = [System.Text.UTF8Encoding]::new($false); [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)` 再管道, 但 shell prompt 和 stderr 仍可能乱(打印不影响执行正确性)。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/database/编码与字符集.md` :: 「PowerShell 管道 `docker exec -i mysql` 把 SQL 中的中文算作 clause 名截断」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

- 附带坑: `docker exec ... mysql -p ...` 在 PS 终端 `[Warning]` 行会被当作 stderr 异常前缀; 用 `2>&1 | Out-String` 包裹更易定位真实出错行。
- 本条是"执行链路传输截断"; 若 SQL 顺利执行完但入库内容是 mojibake, 属客户端会话字符集问题, 见 latin1-client-double-encoding 条目。

## 参考

- 源记录: `docs/known-pitfalls/database/编码与字符集.md` (git 首次收录 2026-09-01)
