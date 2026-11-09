# 机器人新闻雷达 · 本地数据仓（路线 L）

站点：https://jackliu-teadrinker.github.io/ai-news-radar/
本目录是这个雷达的数据主权所在：**全量档案与抓取状态只在这里**，GitHub 上只保留站点需要读的快照。

## 目录结构

```
E:\WIKI数据库\雷达数据\
├── live\                     # 采集工作区（--output-dir 指向这里）
│   ├── latest-24h-min.json   # 24h 精选快照（站点读）
│   ├── arxiv-papers.json     # 学术专区（站点读）
│   ├── custom-anchors.json   # 精选锚点（站点读）
│   ├── government-news.json  # 政策专区（站点读）
│   ├── toutiao-news.json     # 今日头条专区（站点读）
│   ├── wechat-articles.json  # 微信公众号（站点读）
│   ├── source-status.json    # 信源健康（站点读）
│   ├── archive.json          # 21 天滚动档案（站点不读，只留本地）
│   ├── curated\YYYY-MM-DD.json  # 每日精选归档（站点不读，只留本地）
│   ├── gn-url-cache.json     # Google News 跳转缓存（6-7MB，站点不读）
│   ├── seen_urls.json        # 去重状态（站点不读）
│   └── title-zh-cache.json   # 翻译缓存（站点不读）
├── _repo\                    # 发布用 git 工作副本（只含站点快照，约 400KB/次提交）
├── .venv\                    # Python 依赖（feedparser/trafilatura/selectolax/googlenewsdecoder）
├── tools\run-radar.ps1       # 采集 + 发布总控
└── logs\radar-YYYYMMDD.log   # 每轮运行日志
```

## 一轮做了什么

`tools\run-radar.ps1`：

1. 采集（cwd=`_repo`，`RADAR_OUTPUT_DIR=live`）
   - `scripts/update_news.py --output-dir live`：30 个 feed + 摘要提取 + 翻译（约 9-16 分钟）
   - `scripts/arxiv_fetcher.py`、`government_fetcher.py`、`toutiao_fetcher.py`、`curated_collector.py`
2. 守卫
   - 本轮 0 条 → 拒绝发布
   - 本轮 < 已发布条数的一半且已发布 ≥20 条 → 判定源集体故障，拒绝发布
   - 单个专区（arxiv/government/toutiao）本轮 0 条 → 保留仓库里的旧快照，不覆盖
3. 发布
   - 只把 7 个站点快照拷进 `_repo\data`，改 `index.html` 版本号击穿缓存
   - `git commit` + `git push`（经 `http.proxy=127.0.0.1:7897` + `http.version=HTTP/1.1`）
   - 推送到 master 后 GitHub Pages 自动重建（legacy branch 构建，不需要 Actions 跑业务）

## 手动操作

```powershell
cd E:\WIKI数据库\雷达数据\tools
.\run-radar.ps1                 # 采集 + 发布
.\run-radar.ps1 -OnlyPublish    # 只发布 live 现有内容（改完数据想立刻上线时用）
.\run-radar.ps1 -NoPublish      # 只采集，不发布
.\run-radar.ps1 -WindowHours 48 # 改时间窗（默认 24h）
```

计划任务：

```powershell
Get-ScheduledTask radar-local-refresh | Select TaskName,State
Start-ScheduledTask radar-local-refresh          # 立刻跑一轮
Disable-ScheduledTask radar-local-refresh        # 暂停自动更新
Unregister-ScheduledTask radar-local-refresh -Confirm:$false   # 彻底移除
```

## 什么时候会出错

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 日志 `git push 失败` + `Connection was reset` | 直连或 HTTP/2 被重置 | 确认 `Clash` 在跑（127.0.0.1:7897），脚本默认走它；改端口用 `-Proxy` |
| `[SKIP] 上一轮仍在运行` | 上一轮没跑完（锁 45 分钟） | 确认没有卡死的 python 进程，必要时删 `run.lock` |
| `[GUARD] ... 拒绝发布` | 采集塌方（源 503 等） | 看 `logs\` 里同一轮的抓取明细，等下一轮或排查 `source-status.json` |
| 站点长时间不变 | 本机关机 / 任务被禁用 / push 失败 | 每 30 分钟一轮，关机即断更，这是路线 L 的固有代价 |
| Actions 页面报 `disabled` | fork 仓库用量熔断 | 本模式不依赖 Actions 跑业务，Pages 仍能发布；如需恢复云端 workflow，去 Actions 页点 re-enable |

## 和 GitHub 的分工

- **仓库里只有**：站点代码（index.html / assets / scripts / feeds）+ 7 个快照（约 400KB）
- **仓库里没有**（`.gitignore` 挡住）：archive.json、curated/、gn-url-cache.json、seen_urls.json、title-zh-cache.json
- 云端 cron 已停用（`update-news.yml` 与 `keeper.yml` 的 schedule 都注释掉了），只保留 `workflow_dispatch` 作为应急手动入口

## 历史包袱（可选清理）

仓库历史仍有约 5.7GB，是 10 月前每 30 分钟提交 13MB 攒出来的。现在增量已经止住；若要彻底瘦身，可另做一次历史重建（单提交 force push），需要人工确认后执行。

## 快照口径（2026-11-09 修正）

`latest-24h-min.json` 现在是**近 24 小时窗口的并集**（`archive.json` 里还在窗口内的条目 + 本轮新通过筛选的条目），
不再是「本轮新增」。原因：本地 archive 持久化后，第二轮起新条目极少，旧逻辑会把站点从 162 条塌到 14 条（11-09 实测），
GUARD 当场拦下。改动在 `scripts/update_news.py` 的 `snapshot = [it for it in updated if _in_window(it)]`。

各专区文件（arxiv/government/toutiao）另有独立保护：本轮 0 条就保留仓库里的旧快照，不用空数据覆盖。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 正常完成，或命中 GUARD 主动跳过（日志里有 `[GUARD]`） |
| 1 | 真失败（python 崩溃 / 推送失败 / 数据缺失），看 `logs\` |

计划任务里 `LastTaskResult=0` 即表示这一轮正常。

## 自检、指标与心跳（2026-11-09 加）

每轮发布后会自动做三件事，日志里对应三条标记：

| 标记 | 含义 | 失败意味着 |
| --- | --- | --- |
| `[GUARD] data/ 索引体积 xxx KB` | 仓库里被跟踪的 data/ 体积（阈值 2048 KB） | 超过就说明归档文件混回了索引，会重演 5.7GB |
| `[VERIFY] OK/FAIL` | 抓线上 JSON 比对 `generated_at` 与本轮是否一致（最多等 3 分钟） | push 成功但站点没换 = Pages 构建挂了，脚本非零退出 |
| `[BEAT]` | 可选心跳上报 | 传 `-HeartbeatUrl` 才启用 |

每轮还会往 `metrics.jsonl` 追加一行：`ts / items / published / verify_ok / exit_code / elapsed_s`。
想看趋势：`Get-Content metrics.jsonl -Tail 20`。

死信心跳示例（覆盖「机器关机 / 任务被禁用」这种本地无法自报的故障）：

```powershell
# UptimeRobot → Add Monitor → Heartbeat，拿到的 URL 形如 https://heartbeat.uptimerobot.com/xxxxx
Get-ScheduledTask radar-local-refresh | ForEach-Object { $_.Actions[0].Arguments = '-NoProfile -ExecutionPolicy Bypass -File "E:\WIKI数据库\雷达数据\tools\run-radar.ps1" -HeartbeatUrl "https://heartbeat.uptimerobot.com/xxxxx"' }
```

事故复盘与待办清单见 `POSTMORTEM.md`。

## 工具清单（tools\）

| 脚本 | 作用 |
| --- | --- |
| `run-radar.ps1` | 采集 + 发布总控（计划任务每 30 分钟） |
| `doctor.ps1` | 一键体检：依赖 / git 通道 / 线上数据年龄 / 本地 live / 计划任务 / 锁 / 仓库卫生 / 近 24 轮指标 / 日志失败。退出码 0 全绿、1 有 WARN、2 有 FAIL；`-Json` 给机器读 |
| `daily-summary.ps1` | 把 metrics.jsonl 汇总成日报（Markdown），写 `logs\daily-YYYYMMDD.md`，可 `-WebhookUrl` 推送。计划任务 `radar-daily-summary` 每天 09:05 |
| `squash-history.ps1` | 历史瘦身：默认演练（只报体积），`-Execute -ConfirmText SQUASH` 才真跑，默认先做 bundle 备份 |
| `POSTMORTEM.md` | 事故复盘 + 复发定位口诀 |

每天看一样东西就够：`logs\daily-YYYYMMDD.md` 或 `doctor.ps1` 的合计行。

## 归档布局（2026-11-09 整理）

```
live\curated\            每日精选归档，一天一个 JSON。当前 119 天（2026-06-10 ~ 2026-11-09），约 8.4 MB
live\archive.json         21 天滚动条目池（条目级，不是按天切分）
live\imports\legacy-2026-07\   2026-07 那套旧状态快照（archive.json / latest-24h-*.json 等 12 个），只读存档不参与运行
```

**历史缺口**：`2026-07-16 ~ 2026-08-16` 这 32 天在本地没有，只存在于 GitHub 的 commit 历史里。
另外「每 30 分钟一轮的完整快照」（约 9900 份 latest-24h-min）也只在 GitHub 历史里，本地只留每日定版。

### ⚠ 顺序很重要

要做 `squash-history.ps1` 之前，先把需要的历史从 GitHub 导出来。
历史一旦被压缩改写，那些逐轮快照就永久拿不回来了。
导出思路：遍历 master 的 commit，每天取最后一个 `data/latest-24h-min.json`，写成 `live\history\YYYY-MM-DD.json`。

## 方案C：按日分片（2026-11-09 上线）

**问题**：每轮（约 48 次/天）全量重写 `latest-24h-min.json`（190 KB），3 个月把 git 历史撑到 5.8 GB，而真实内容只有 8.4 MB。

**现在的形态**：

```
data/days/index.json           列出所有日期 + 本轮 generated_at（前端入口，约 150 B）
data/days/YYYY-MM-DD.json      当天发布的条目，一条一行（约 200 KB/天，跨零点自动归到前一天）
data/latest-24h-min.json       前端兜底，每天定版一次（不再每轮重写）
```

- 后端按 `published_at` 的本地日期归档，只追加不重排；文件"一条一行"，git 可以按行做 delta，
  未变动的条目是逐字节相同的行 → 每轮只存新增那几行。
- 前端 `loadNewsData()` 先读 `index.json` + 最近 2 天分片，按 url 合并去重、客户端算 `site_stats`；
  条目 <80 时自动补取第 3 天。任何失败回退 `latest-24h-min.json`，不会白屏。
- `assets/app.js` 里有 `USE_DAY_SHARDS = true` 开关，改 false 并重新发布即可一键回退。
- 分片超过 60 天移出仓库到 `live\days-archive\`（历史不丢，只是不再随站点发布）。

**注意**：默认不要手动用云端 workflow 跑数据。云端已改为热备（见下节），日常采集由本机计划任务负责。
仓库根目录建一个 `.radar-local-mode` 可让云端彻底停手（11-09 13:48 就发生过一次云端 dispatch
把历史分叉、并把 30 条的 arxiv 覆盖成 0 条）。

## 云端热备（2026-11-09 启用）

云端 workflow 是**热备**：cron 每小时一拍（`0 * * * *`），本地在跑时几乎不消耗 runner。

判断顺序（`Gate` 步骤，checkout 后立即执行，不满足就整 job 跳过）：

| 条件 | 结果 |
| --- | --- |
| 仓库根目录存在 `.radar-local-mode` | 整个 job 几秒结束，云端永不推送 |
| 最近一次提交作者是 `radar-local` 且不到 45 分钟 | 云端让位（本机在跑，云端不抢分支） |
| 以上都不满足（本机停了 45 分钟以上） | 云端接管，抓取 + 生成分片 + 推送 |

推送前还有第二道闸（`Auto-push` 步骤的 `[HANDOFF]`）：40 分钟内有过 `radar-local` 提交就让位。
抓取可以重复，推送必须单点。

实测（2026-11-09，两个方向都真跑过）：

| 场景 | 耗时 | 日志证据 |
| --- | --- | --- |
| 本机在跑，云端被触发 | 4s | `[GATE] 最近提交作者=radar-local 距今=…` → 13 个步骤全跳过 |
| 本机停跑 55min，云端被触发 | 2m40s | `[GATE] …距今=3320s` → `[HANDOFF] 本机已有 57 分钟没推过，云端接管本轮推送` |
| 接管那一轮的产出 | — | `[STATE] 479 条自举 / gn-url-cache 77 条（cache 命中）`、`[SHARD] 2026-11-09 新增 5 条 → 441`、`[KEEP] arxiv 0 条还原 30 条`、提交 `7fdc4c8 [radar-auto]` |
| 本机恢复后 | — | `[SYNC] 已对齐 origin/master：54d828d -> 7fdc4c8（云端接管过，本机追平）` → 推 `1749650 [radar-local]` |
| 每小时一次合计 | ≈40min/天 | 远低于最初触发 fork 熔断的 ~2.4h/天 |

### ⚠ GitHub cron 在本仓库靠不住（2026-11-09 实测）

`schedule` 事件被 GitHub 大规模丢弃，这是 fork 的老问题：本仓库历史每天只跳 5-12 次
（而 `*/30` 理论上该有 48 次），11-09 全天 **0 次**——`0 * * * *` 定到 10:00Z
等了 42 分钟也没跳。所以**别把 cron 当成保命机制**，它只是"白捡一次"。

真正在保命的是本机 Hermes cron：

| 组件 | 周期 | 作用 |
| --- | --- | --- |
| Windows 任务 `radar-local-refresh` | 30min | 主链路，本地采集 + 发布 |
| Hermes cron `radar-freshness-watchdog`（`radar_watchdog_v2.py`） | 15min | 外部哨兵：发现线上数据 >45min 就 `workflow_dispatch` 云端接管，40min 冷却防连环 |

所以本机一停的现实接管延迟是 **45min（阈值）+ ≤15min（巡检）≈ 1 小时**，不依赖 GitHub cron。

**哨兵口径（2026-11-09 修正）**：watchdog 原来读 `data/latest-24h-min.json` 的
`generated_at`。但本地管线对 24h 快照做"今日定版"（当天只写一次，之后每轮只更新分片），
于是该字段会被冻在当天第一次定版的时刻（实测 07:49Z 定版 → 10:45Z 报 176min），
而线上真实更新时间在 `data/days/index.json`（同一时刻只有 29min）。
结果：watchdog 误判 stale，冷却一过就 dispatch 一次，一天白烧 ~30 次 runner 且长期红着。
现已改为"分片索引优先、24h 快照兜底"，取最年轻的那个。
**任何外部监控（UptimeRobot 等）都必须读 `data/days/index.json`，不要读 `latest-24h-min.json`。**

### 本机自愈

云端接管后会多一个 `[radar-auto]` 提交，本机如果直接 push 会被拒（non-fast-forward），
而且此后每轮都失败 → 本机静默掉队。`run-radar.ps1` 现在每轮发布前先
`git fetch + reset --hard origin/master`（`[SYNC]`），追上就继续，fetch 失败也不阻断本轮。

**手动关掉云端**：在仓库根建一个空文件 `.radar-local-mode` 并提交（紧急开关）。
**手动切纯云端**：`Disable-ScheduledTask -TaskName 'radar-local-refresh'`，其余交给 cron + watchdog。

**手动关掉云端**：在仓库根建一个空文件 `.radar-local-mode` 并提交（紧急开关）。
**手动切纯云端**：`Disable-ScheduledTask -TaskName 'radar-local-refresh'`，其余交给 cron。

云端状态处理（解决 runner 无状态）：
- `seen_urls` / `title-zh-cache` / `archive` 由 `scripts/rebuild_state.py` 从 `data/days/*.json` 重建，零外部依赖
- `gn-url-cache`（6.3MB，GN 跳转解析结果，快照里没有）走 `actions/cache`，每轮存新 key + 前缀恢复
- 专区快照（arxiv / government / toutiao）本轮 0 条时从 HEAD 还原，不会把好数据覆盖成空
