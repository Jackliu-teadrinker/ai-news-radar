# 🤖 AI News Radar

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/badge/Actions-Running-blue?style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions)
[![Self-Healing](https://img.shields.io/badge/Watchdog-Dual--Layer-orange?style=flat-square)](#双层自愈看门狗)
[![Issues](https://img.shields.io/badge/Issues-Disabled-lightgrey?style=flat-square)](#问题跟踪说明)

[English](README.en.md) · [在线访问](https://jackliu-teadrinker.github.io/ai-news-radar/)

---

## 这是什么

人形机器人 / 具身智能 / 脑机接口 / 物理 AI 领域的全球新闻雷达。每 30 分钟由 GitHub Actions 自动采集、评分、去重并部署，覆盖国内外中英文信源，全自动运行，无需人工干预。

**当前规模（2026-09-10）：**

| 维度 | 数据 |
|---|---|
| 总信源 | 58 个 feed |
| 有效信源 | 56 个（97%）|
| 24h 数据量 | ~880 条 → 去重 ~80 条 → 噪声过滤 ~38 条 |
| 主题锚点 | 5 大主题：国内具身智能 / 国内人形机器人 / 国内脑机接口 / 国内机器人 / 国外机器人+物理AI+具身智能 |

**页面板块：**

| 板块 | 数据文件 | 来源 |
|------|----------|------|
| 📰 机器人信号流 | `latest-24h-min.json` | Google News 10 组 RSS + 精选媒体 |
| 📱 微信公众号 | `wechat-articles.json` | 手动维护 + Exa MCP 搜索 |
| 🏛️ 政策专区 | `government-news.json` | 政府官网 |
| 🎓 学术专区 | `arxiv-papers.json` | arXiv cs.RO |
| 🔗 精选锚点 | `custom-anchors.json` | TechCrunch/IEEE/量子位等 |

---

## 数据是怎么更新的

数据生产**完全在 GitHub 云端**，不依赖任何本地电脑：

```
update-news.yml（唯一生产者）
  ├─ schedule 触发：每 30 分钟
  ├─ push 触发：修改信源/代码后自动部署
  └─ workflow_dispatch：watchdog 补救 / 人工触发
         ↓
  抓 RSS → 评分/去重/时间窗口过滤 → commit → GitHub Pages 部署
```

---

## 双层自愈看门狗

GitHub Actions 的 schedule 存在平台级**间歇性掉拍**问题（可能延迟几分钟到几小时，曾实测连续 3 拍未触发）。为此雷达配了两层互相独立的 watchdog，专治"该更新没更新"：

### 第一层：云端 keeper（`.github/workflows/keeper.yml`）

跑在 GitHub Actions 上，**本地电脑关机也在岗**。每 20 分钟一次（每小时的 :07 / :27 / :47，与主任务的 :00/:30 错峰）：

1. 检查 Pages 数据年龄，`generated_at` 超过 **45 分钟**视为 stale
2. 确认主任务没有排队/进行中/近 20 分钟内的 run（**防级联 dispatch**）
3. 满足条件 → 用内置 `GITHUB_TOKEN` dispatch 主任务补跑
4. 顺手 re-enable 两个 workflow，防 GitHub「60 天不活跃自动禁用 schedule」陷阱

权限仅 `contents: read` + `actions: write`，零外部依赖，无需配置任何 secret。

### 第二层：本地 watchdog（可选）

本地电脑开机时在岗：Hermes cron 每 15 分钟运行 `radar_watchdog_v2.py`，双源取更新者（本地缓存 vs Pages），stale 且不在 25 分钟冷却期内 → dispatch 主任务。与云端 keeper 互为备份。

### 延迟预期

| 场景 | 最坏延迟 |
|---|---|
| 正常（schedule 准时触发） | ≤ 30 分钟 |
| schedule 掉拍，云端 keeper 在岗（默认） | ~20 分钟（发现 + 补跑） |
| 两个 watchdog 都失效 | 等下次 schedule 自然醒来（不可控） |

> 注：watchdog 不生产数据，只是"监工"——发现卡住就踹主任务一脚。页面是静态托管，数据过期时页面仍能打开，只是内容变旧；看 `generated_at` 才是真新鲜度。

---

## 快速开始

访问主页：https://jackliu-teadrinker.github.io/ai-news-radar/

本地运行：

```bash
git clone https://github.com/Jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
```

---

## 修改信源

编辑 `feeds/follow.example.opml`（主区块）或 `feeds/custom.opml`（锚点专区），commit 后自动触发部署。

信源健康度在每次采集后写入 `data/source-status.json`（58 条记录，含 success / items_unique / error），可作为失效源诊断依据。

---

## 诊断

```bash
# Pages 数据新鲜度（破缓存）
curl -s "https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json?cb=$(date +%s)" \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('generated_at'), d.get('total_items'), 'items')"

# 当前信源健康度（成功/失败/0条）
curl -s "https://jackliu-teadrinker.github.io/ai-news-radar/data/source-status.json" \
  | python -c "import sys,json; d=json.load(sys.stdin); print('ok:', sum(1 for f in d['feeds'] if f['success']), '/', len(d['feeds']))"

# 云端 keeper 最近运行
gh run list -R Jackliu-teadrinker/ai-news-radar --workflow=keeper.yml --limit 5

# 主任务最近运行
gh run list -R Jackliu-teadrinker/ai-news-radar --workflow=update-news.yml --limit 5
```

---

## 已知问题与修复历史

| 问题 | 状态 | 真实情况 / 根因 |
|---|---|---|
| #26 workflow concurrency 互抢 | ✅ 2026-08-27 根治 | schedule 独立 concurrency group，永不互抢 |
| #31 GitHub cron 间歇性掉拍 | ✅ 双层 watchdog 兜底 | 平台问题无法根治，缓解到最坏 ~20 分钟 |
| 本地 watchdog 静默失效 5 天 | ✅ 2026-09-04 根治 | 僵尸缓存阻塞判定 + 采集器挂死崩溃传播 |
| **#10 RSS 静默 0 items** | ⚠️ **名实不符，已查根因** | 实际是 **2 个 RSS 源 HTML 解析失败**（`VentureBeat AI` / `TechXplore Robotics`），不是真 0 条；56/58 源覆盖良好。修法：换 URL 或改 parser 跳过 |
| #27 Google News 集体 503 | ⚠️ 未根治 | keeper 防级联 dispatch 已缓解，GN 仍偶发；根治需重试+退避+多源备份 |

---

## 问题跟踪说明

> ⚠️ **GitHub Issues 已禁用（2026-09）**——仓库的 Issues 功能被关闭。

- **当前跟踪方式**：本 README 的"已知问题与修复历史"表 + 每个修复的 commit message
- **新增 bug 报告**：直接在 commit message 里写 `fix(#X): <一句话根因>`，并在 PR description 里写上下文
- **修复历史可查**：浏览仓库 commit log（搜索 `fix:`、`根治`、相关 issue 号）

---

## License

MIT