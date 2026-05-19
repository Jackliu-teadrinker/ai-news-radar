# 机器人新闻雷达 · Humanoid Robot News Radar

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/github/actions/workflow/status/Jackliu-teadrinker/ai-news-radar/update-news.yml?branch=master&label=update&style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions/workflows/update-news.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)

[在线站点](https://jackliu-teadrinker.github.io/ai-news-radar/) · [English](README.en.md)

---

## 这是什么

**人形机器人/具身智能专项新闻雷达**。

自动追踪全球人形机器人、具身智能、脑机接口、物理 AI（Physical AI）等领域的新动态，每天 09:00 - 20:00 区间每 30 分钟更新，数据覆盖前一天 9AM 至当前最新。

## 功能特性

- **每 30 分钟自动更新**：GitHub Actions 驱动，零人工值守
- **双语标题**：英文内容自动翻译为中文，标题对照阅读
- **行业专项过滤**：过滤股票涨跌、ETF、扫地机器人、快讯/短新闻等噪声
- **Relevance 评分**：按行业相关性排序，重要文章优先展示
- **多信源覆盖**：Google News 英文 ×5 + 中文 ×5 + TechCrunch + 36kr，共 10 条 RSS 源
- **归档去重**：21 天归档，SWA1(title+url) 全局去重，避免重复推送

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
├── latest-24h-min.json   # AI 精选视图（ Relevance > 0.4，≤50 条）
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
│   └── update_news.py         # 采集脚本
├── data/
│   └── *.json                 # 输出数据（GitHub Pages 读取）
├── .github/workflows/
│   └── update-news.yml        # 30min 自动更新 + 部署
└── README.md
```

## License

[MIT](LICENSE)
