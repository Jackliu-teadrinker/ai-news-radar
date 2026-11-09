# radar-watchdog — 雷达外部哨兵

## 为什么需要它

2026-11-07 起站点停更 51 小时，根因是 **GitHub 以「fork 仓库 Actions 用量规模过大」为由，把这个仓库的全部 workflows 停掉了**。
仓库内的 `keeper.yml` 本来自带新鲜度巡检，但它和业务跑在同一条链上——Actions 一停，哨兵和抓取一起静默，没人报警。

哨兵必须跑在 GitHub 之外。

## 两个可用形态

| 形态 | 常在线 | 依赖 | 适合 |
| --- | --- | --- | --- |
| Cloudflare Worker（`index.js` + `wrangler.toml`） | ✅ | 一个 CF 账号 + fine-grained PAT | 主用 |
| 本地任务计划（`local-watchdog.ps1`） | ❌ 机器要开着 | 本机 `gh` 已登录 | 兜底 |

两套逻辑一致：读 Pages 的 `data/latest-24h-min.json` → 算 `generated_at` 年龄 →
超过 90 分钟就补 dispatch → dispatch 返回 422「disabled」说明 Actions 被停，直接告警并给出 re-enable 链接。

## 部署 Worker

```bash
cd workers/radar-watchdog
npm i -g wrangler          # 或 npx wrangler
wrangler login

# PAT：fine-grained，Repository access 选 ai-news-radar，权限 Actions = Read and write
wrangler secret put GH_PAT
wrangler secret put ALERT_WEBHOOK_URL   # 可选，接收 {"text": "..."}，企业微信/飞书/Telegram 中转都行

wrangler deploy
curl "https://radar-watchdog.<your-subdomain>.workers.dev/check"   # 手动体检一次
```

`wrangler.toml` 里 cron 是 `*/30 * * * *`；阈值 `WARN_MIN=90`、`CRIT_MIN=180` 分钟，按需改常量。

## 注册本地兜底

```powershell
schtasks /create /tn "radar-watchdog" /sc minute /mo 30 /f `
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PWD\local-watchdog.ps1`""
```

日志落在 `%LOCALAPPDATA%\radar-watchdog\watchdog.log`。

## 收到告警时怎么办

1. 打开 <https://github.com/Jackliu-teadrinker/ai-news-radar/actions>，看顶部黄条
   「Workflows are not currently being run on this fork due to the scale of GitHub Actions usage」。
2. 点黄条里的 re-enable（只能界面点，API 的 `PUT /actions/permissions` 对 fork 熔断无效）。
3. 再跑一次 `curl .../check`，确认 `dispatch_ok` 且 age 回落。
