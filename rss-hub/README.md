# RSSHub 接入参考（今日头条专区绕行方案）

> 本目录是**文档 + 可复现脚本**，不是运行时依赖。它固化了「自托管 RSSHub → 绕过头条号反爬 → 拿到真·头条号内容」这条已验证的路径，供以后有常驻环境时接入雷达头条专区。
>
> **现状**：雷达头条专区目前走 Google News 中文搜索（`scripts/toutiao_fetcher.py`），与主信号流国内桶高度重合。RSSHub 头条路由能抓到**真头条号内容**（内部调 `toutiao.com/api/pc/list/feed` + `a_bogus` 签名，绕过登录墙/验证码/反爬），两者互补。

## 已验证结论（2026-10-21 本地实测）

- 本地 `pnpm install`（node v26 兼容 RSSHub engines `^22/^24`，非严格只 warn）约 3 分钟装好。
- `pnpm run dev` 起服务后，`GET /toutiao/channel/news_tech` 真返回「科技 - 今日头条」频道的一批头条号文章，反爬绕过成功。
- **新版 RSSHub 1.0.0 路由已重构**：旧版 `/toutiao/search/article/`（按关键词搜）已删除，现在是：
  - `/toutiao/channel/:category` — 频道（推荐/热点/科技/财经/数码/视频…，20 个）
  - `/toutiao/user/token/:token` — 指定头条号作者主页

## 本地一键起（临时验证用）

```bash
# 需本地有 node>=22 和 npm（会装 pnpm）
bash rss-hub/start-local.sh            # 前台起在 :1200，Ctrl+C 停
# 可选 env:
#   RSSHUB_DIR=~/.cache/ai-radar-rsshub   源码+依赖目录（默认值）
#   RSSHUB_PORT=1200                       监听端口（默认 1200）
#   GIT_PROXY=http://127.0.0.1:7897       出网走 Mihomo 代理时才设
```

## 探测验证（确认服务通 + 反爬绕过成功）

```bash
bash rss-hub/probe-toutiao.sh                          # 默认 :1200 拉 news_tech
bash rss-hub/probe-toutiao.sh http://127.0.0.1:1201    # 指定别的端口
bash rss-hub/probe-toutiao.sh http://127.0.0.1:1200 news_hot   # 拉热点频道
# 成功输出 "✓ 真 RSS，头条频道 ... 绕过 a_bogus 反爬成功" + 前几条 title
```

## 接入雷达（B / C 路线，需常驻环境）

前提：RSSHub 需**常驻**跑在某处（VPS / 一直开着的机器 / Docker / Cloudflare Worker），因为它是 HTTP 服务，不是纯 RSS 端点。每次云 cron 现起太重（`pnpm install` 要 3 分钟，不稳）。

- **B 单源接入**（最小改动）：起好 RSSHub 后，把频道当一个独立 feed 接进头条专区。`toutiao_fetcher.py` 里加一个源指向 `http://<rsshub-host>/toutiao/channel/news_tech`（RSS，feedparser 可解析），与现有 GN 中文搜索**并行**，前端 `source` 标成「头条号·科技」。
- **C 频道版全替换**（贴合原设想）：头条专区改抓 3 个 RSSHub 频道（`news_tech` 科技 / `news_hot` 热点 / `digital` 数码），**彻底替换** GN 中文搜索。此时「今日头条」专区名副其实，与主信号流不再同源。

## 常驻部署参考

```bash
# Docker（最省事，一条命令常驻）
docker run -d --name rsshub -p 1200:1200 diygod/rsshub:latest
# 之后 B 路线就把 feed 指向 http://<vps-ip>:1200/toutiao/channel/news_tech

# Cloudflare Worker / Pages + Worker：RSSHub 官方支持 worker 部署
# 参考 https://docs.rsshub.app/installation/（Worker 段）—— 免维护常驻
```

## 已知坑

- **node 版本**：RSSHub engines 要求 `^22.22.2 || ^24.15.0`；node v26 能装能跑（非严格 engines 只 warn），但生产建议钉 22/24。
- **出网**：本机 clone GitHub 有时被挡，配 `GIT_PROXY=http://127.0.0.1:7897`（Mihomo）可通。
- **反爬已内置**：RSSHub 头条路由自带 `a_bogus` 签名，你不用碰验证码/登录；但高频抓取仍可能限流，常驻实例建议加 RSSHub 自带缓存（默认有）。
- **头条接口易变**：`toutiao.com/api/pc/list/feed` + `a_bogus` 是字节接口，上游改签名逻辑时 RSSHub 社区会跟进，保持 RSSHub 版本更新（`git pull && pnpm install`）。
