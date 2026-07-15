# 人形机器人/具身智能新闻雷达 · Humanoid Robot News Radar

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/badge/Actions-Running-blue?style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions)
[![Update Frequency](https://img.shields.io/badge/Update-Every%2030min-purple?style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)

[在线站点](https://jackliu-teadrinker.github.io/ai-news-radar/) · [English](README.en.md)

---

## 这是什么

**人形机器人 / 具身智能 / 脑机接口 / 物理 AI 领域的全球新闻雷达。**

自动追踪人形机器人、具身智能、脑机接口、物理 AI（Physical AI）等领域的全球最新动态，每 30 分钟自动更新，覆盖前一天 9AM 至当前最新。

## 运行数据

| 指标 | 数值 |
|------|------|
| Actions 总运行次数 | 2296+ |
| 更新时间间隔 | 每 30 分钟 |
| 信源数量 | 10+ RSS 源 |
| 归档周期 | 21 天 |
| 仓库大小 | 5.9 MB |
| 覆盖语言 | 中文 + 英文（自动翻译） |

## 功能特性

- **每 30 分钟自动更新**：GitHub Actions 驱动，零人工值守
- **双语标题**：英文内容自动翻译为中文，标题对照阅读
- **行业专项过滤**：过滤股票涨跌、ETF、扫地机器人、快讯/短新闻等噪声
- **Relevance 评分**：按行业相关性排序，重要文章优先展示
- **多信源覆盖**：Google News 英文 ×5 + 中文 ×5 + TechCrunch + 36kr，共 10 条 RSS 源
- **归档去重**：21 天归档，SHA1(title+url) 全局去重，避免重复推送
- **健康监控**：独立 Watchdog 自动检测雷达健康状态

## 覆盖领域

| 分类 | 信源 |
|------|------|
| 人形机器人 | GN: humanoid robot / 国外人形机器人资讯 |
| 具身智能 | GN: embodied intelligence / GN: 具身智能 |
| 脑机接口 | GN: BCI / GN: 脑机接口 |
| 物理 AI | GN: Physical AI / GN: 物理AI |
| 机器人综合 | GN: robot / 国外机器人资讯 |
| 行业媒体 | TechCrunch、36kr |

## 快速开始

直接访问：[https://jackliu-teadrinker.github.io/ai-news-radar/](https://jackliu-teadrinker.github.io/ai-news-radar/)

本地运行：

```bash
git clone https://github.com/jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
# 打开 http://localhost:8080
```

修改信源：编辑 `feeds/follow.example.opml`，添加/删除 RSS 源后 commit 即可自动部署。

## 数据输出

```
data/
├── latest-24h-min.json   # AI 精选视图（Relevance > 0.4，≤50 条）
├── latest-24h-all.json   # 全量视图（全部去重条目）
├── source-status.json    # 各信源健康状态
└── archive.json          # 21 天归档
```

## GitHub Actions

`.github/workflows/update-news.yml` 已预配置：

- cron: `*/30 * * * *`（每 30 分钟）
- push 触发（任何 commit 自动运行）
- `workflow_dispatch`（手动触发）
- 自动 commit 数据文件 + Pages 部署

手动触发：
```bash
gh workflow run update-news.yml --repo Jackliu-teadrinker/ai-news-radar
```

## 项目结构

```
ai-news-radar/
├── feeds/
│   └── follow.example.opml    # RSS 信源配置
├── scripts/
│   ├── update_news.py         # 采集脚本
│   ├── update_news_v2.py      # v2 采集脚本（15 分类体系）
│   ├── curated_collector.py   # 精选文章收集器
│   └── ai_relevance.py        # 相关性评分
├── data/
│   └── *.json                 # 输出数据（GitHub Pages 读取）
├── assets/
│   ├── index.html             # 前端页面
│   ├── app.js                 # 前端逻辑
│   ├── styles.css             # 样式表
│   └── logo.svg               # Logo
├── .github/workflows/
│   ├── update-news.yml        # 30min 自动更新 + 部署
│   ├── update-news-v2.yml     # v2 采集流水线
│   ├── radar-watchdog.yml     # 健康监控
│   ├── gh_auto_push_data.py   # 数据自动推送
│   ├── gh_push_data.py        # 数据推送（备用方案）
│   └── update-index-version.py # 缓存版本更新
└── README.md
```

## License

[MIT](LICENSE)
