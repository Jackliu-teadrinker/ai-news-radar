# 雷达停更事故复盘 & 韧性清单

事故：2026-11-07 07:50 ~ 2026-11-09 12:03（本地时间），站点数据冻结 52 小时无人发现。

## 一、根因链（五层，缺一层都不会停 52 小时）

1. **平台侧熔断**：仓库是 `LearnPrompt/ai-news-radar` 的 fork，累计 9903 次 workflow run、仓库 5.7 GB。
   GitHub 对 fork 仓库的 Actions 用量有规模限制，触发后**整仓 workflows 停用**，连 `workflow_dispatch` 都返回 422。
2. **哨兵与业务同链**：`keeper.yml` 每 15 分钟查一次数据年龄、stale 就补 dispatch —— 但它自己就是 workflow，
   Actions 一停，哨兵和业务一起死。**这是整起事故最致命的架构缺陷**。
3. **无外部观测**：没有任何 GitHub 之外的探针读 `generated_at`，所以「全链路静默」对外零信号。
4. **阈值不可见**：fork 用量阈值没有 API、没有仪表盘，触发前只有一封容易被忽略的邮件。
5. **数据膨胀是自找的**：每轮提交 13 MB（`gn-url-cache.json` 6.2MB + `curated/` 6.6MB），
   48 轮/天 × 数月 → 5.7 GB。**不是被平台惩罚，是自己把仓库喂到了阈值上**。

## 二、四个隐性放大器（不致命，但让问题更糟）

| 现象 | 代价 |
| --- | --- |
| Pages 双部署链（legacy branch 构建 + workflow 里 `deploy-pages`） | 两条链抢同一个 deployment，`in progress deployment` 直接失败 |
| cron `*/30` + `*/15` 实测命中率仅 ~30% | 「每 30 分钟更新」实际是「每 1-3 小时更新」 |
| `refresh_anchors.py` 写死 `C:\Users\...\ai-news-radar` | 云端 Linux runner 上必然指不到，该字段**长期静默为空**，没人发现 |
| 大量失败 run 无人看 | 失败被 normalize 成常态，真事故淹没在噪声里 |

## 三、现在的防线（对应上面每一条）

| 问题模式 | 现在的机制 | 位置 |
| --- | --- | --- |
| 哨兵与业务同链 | 采集搬到本机，GitHub 只做静态托管；数据年龄由外部可读的 `generated_at` 判断 | `tools/run-radar.ps1` |
| push 成功但站点没更新 | **发布后自检**：抓线上 JSON 比对 `generated_at`，不一致直接 FAIL 非零退出 | 同上 `[VERIFY]` |
| 仓库无界膨胀 | `data/` 只留 8 个站点快照；`.gitignore` 挡归档；发布前断言归档文件没回到索引 + 索引体积阈值 | 同上 `[GUARD]` |
| 坏数据覆盖好数据 | 三重守卫：本轮 0 条拒发、<50% 拒发、单专区 0 条保留旧快照 | 同上 |
| 只能事后翻日志 | 每轮写一行 `metrics.jsonl`（条数/是否发布/自检结果/耗时） | `metrics.jsonl` |
| 配置漂移 | 本机绝对路径已清除；`--output-dir` 参数化 | `scripts/*` |
| 平台限制不可控 | 业务不再依赖 Actions；Pages 构建仍由 GitHub 侧负责，但即使 Actions 停用也能发布（11-09 验证） | — |

## 四、还没做的（按性价比排序）

### P0（建议尽快，成本 ≤ 半天）

1. **死信心跳**：本机每轮发布成功后 POST 一个心跳 URL（UptimeRobot 免费心跳监控 / Cloudflare Worker KV）。
   超过 90 分钟没心跳就发告警。覆盖「机器关机、任务被禁用、脚本卡死」——这是当前唯一残留的静默面。
   脚本已留接口：`.\run-radar.ps1 -HeartbeatUrl "https://..."`。
2. **历史压缩**：单提交重建 + force push，把仓库从 5.7 GB 降到约 15 MB。
   需要人工确认（丢历史 commit）。不压缩也能跑，但 `git clone` 和 Pages 构建都会一直背着这个包袱。

### P1（有价值，可排期）

3. **发布镜像**：同一份 `_repo` 产物再推一份到 Cloudflare Pages（`wrangler pages deploy`），
   GitHub Pages 出问题时可切域名/切 CDN，且彻底摆脱 Actions 依赖。
4. **前端数据源兜底**：`assets/app.js` 的 fetch 加备用 URL（主源失败重试一次到镜像域名），
   避免单一 host 故障导致白屏。
5. **每日简报**：把 `metrics.jsonl` 汇总成一行日报（多少轮、几轮被 GUARD 拦、平均耗时、源成功率）推到微信/Telegram。
   目的是让「异常成为可见的趋势」而不是等 52 小时后才发现。

### P2（长期卫生）

6. **在健康的非 fork 仓库跑 CI**：`tech-news-radar` 的 Actions 是好的，可以在那里跑
   「yaml 解析 + python 编译 + 小样本烟测」校验 `ai-news-radar` 的脚本，替代被停用的云端 CI。
7. **GUARD 自适应**：现在一刀切「<50% 拒发」。可改为按分区判定（政策/头条/学术各自阈值），
   减少「一个专区塌方导致整轮不发」的误伤。
8. **归档冷存**：`live/curated/` 按月打包 zip、`archive.json` 按周留快照，控制本地目录长期体积。

## 五、下次再停更，5 分钟定位流程

```powershell
# 1. 站点到底停在哪一刻
(Invoke-RestMethod 'https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json?cb=1').generated_at

# 2. 本机任务是否还在跑
Get-ScheduledTask radar-local-refresh | Select State
Get-ScheduledTaskInfo radar-local-refresh | Select LastRunTime,LastTaskResult,NextRunTime

# 3. 最近几轮发生了什么
Get-Content "E:\WIKI数据库\雷达数据\logs\radar-$(Get-Date -Format yyyyMMdd).log" -Tail 40
Get-Content "E:\WIKI数据库\雷达数据\metrics.jsonl" -Tail 10

# 4. 手动补一轮
Start-ScheduledTask radar-local-refresh      # 或 cd tools; .\run-radar.ps1
```

判读口诀：
- 有 `[VERIFY] OK` 但站点旧 → 前端缓存/CDN，查 `index.html` 版本号
- 有 `[PUBLISH] 推送成功` 无 `[VERIFY]` → Pages 构建卡住
- 有 `[FAIL] git push` → 代理（Clash 7897）或 `http.version`
- 有 `[GUARD]` 无 `[FAIL]` → 数据被主动拦下，不是故障，看源健康
- 什么都没写 → 任务没跑起来，查任务计划程序历史与锁文件 `run.lock`
