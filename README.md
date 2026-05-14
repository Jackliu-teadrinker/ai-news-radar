# 机器人新闻雷达 · AI News Radar

Forked from [robot-news-radar](https://github.com/LearnPrompt/ai-news-radar) · 已配置 53+ 个机器人/RSS 数据源

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/github/actions/workflow/status/Jackliu-teadrinker/ai-news-radar/update-news.yml?branch=master&label=update&style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions/workflows/update-news.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)

[在线站点](https://jackliu-teadrinker.github.io/ai-news-radar/) · [English](README.en.md) · [Scout Skill](skills/ai-news-radar/README.md)

---

## 这是什么

机器人新闻雷达是一个**自动化更新的 24 小时机器人/具身智能资讯监控页面**。

打开页面即可浏览最近 24 小时全球机器人、人形机器人、具身智能、脑机接口等领域的最新动态。fork 本项目后可接入自己的 OPML/RSS 订阅源，打造专属资讯雷达。

本项目的核心不是"又一个新闻聚合页"，而是 **Scout Skill（侦察技能）**——帮助你在海量信息源中识别真正值得长期追踪的优质来源，屏蔽噪声源。

## 功能特性

- **24h 自动更新**：GitHub Actions 每 30 分钟自动抓取，数据始终新鲜
- **双语标题**：英文内容自动翻译为中文，标题对照阅读
- **AI 相关性过滤**：自动识别高相关性内容，过滤噪声
- **OPML/RSS 批量订阅**：将自己的 RSS 源导入，打造专属雷达
- **多视图切换**：AI 精选视图 / 全量视图，按需切换
- **信源健康监控**：实时追踪各来源的更新频率和覆盖质量
- **零成本部署**：核心流程无需 LLM API key，纯规则运行

## 快速开始

直接访问：[https://jackliu-teadrinker.github.io/ai-news-radar/](https://jackliu-teadrinker.github.io/ai-news-radar/)

本地运行：

```bash
git clone https://github.com/Jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
# 打开 http://localhost:8080
```

接入自己的 OPML 订阅：

```bash
# 1. 将自己的 RSS 订阅导出为 OPML 文件
# 2. 放到 feeds/follow.opml（不要提交到公开仓库）
# 3. 运行时指定 OPML 文件
python scripts/update_news.py --output-dir data --window-hours 24 --rss-opml feeds/follow.opml
```

## 数据源配置

项目支持多种数据源接入方式，通过环境变量或 GitHub Secrets 配置：

| 变量 | 说明 | 默认 |
|------|------|------|
| `FOLLOW_OPML_B64` | Base64 编码的 OPML 文件（隐私） | follow.example.opml |
| `RSS_MAX_FEEDS` | 最大 RSS 源数量（0=无限制） | 0 |
| `DISABLE_BUILTINS` | 禁用内置数据源 | 0 |
| `X_API_ENABLED` | 启用 X (Twitter) API | 0 |
| `X_BEARER_TOKEN` | X API Token | - |

详细配置示例见 `examples/advanced-sources.env.example`。

## 工作原理

```
数据源列表
    ↓
Scout Skill 分类识别
    ↓
RSS/Changelog → 公共 OPML → GitHub JSON → 静态页面 → 跳过风险源
    ↓
抓取 + 去重 + AI相关性过滤
    ↓
data/*.json + GitHub Pages Web UI
```

信源分为五类：
1. **官方 RSS/Changelog**：公司官方博客、发布日志
2. **私人 OPML/RSS**：用户自己的订阅源
3. **公共 GitHub Feed**：GitHub 项目的 release/issue 动态
4. **静态页面**：无 RSS 的公开页面，Jina 读取
5. **邮件订阅**：通过 AgentMail 接入高质量 Newsletter

## GitHub Actions 自动化

`.github/workflows/update-news.yml` 已预配置：

- 每 30 分钟自动更新（cron: `*/30 * * * *`）
- 自动提交 `data/*.json` 到 master 分支
- 自动部署到 GitHub Pages
- 无 API key 时使用公开演示 OPML 运行

手动触发：在 GitHub Actions 页面点击 `Update AI News Snapshot` → Run workflow

## 机器人行业专用配置

本 fork 在原版基础上针对机器人行业优化：

- 53+ 机器人/具身智能专业 RSS 源
- 人形机器人、协作机器人、医疗机器人、核心零部件专项覆盖
- 脑机接口（BCI）专项追踪
- 投融资动态关键词监控
- 支持接入微信公众号、微博等中文源

## 项目结构

```
ai-news-radar/
├── data/                    # 生成的 JSON 数据文件
│   ├── latest-24h.json      # 24h 最新数据（GitHub Pages 读取）
│   └── archive.json          # 历史归档
├── feeds/
│   ├── follow.example.opml   # 演示 OPML（公开）
│   └── follow.opml           # 私有 OPML（不提交）
├── scripts/
│   └── update_news.py        # 核心抓取脚本
├── skills/
│   └── ai-news-radar/        # Scout Skill（AI Agent 维护指南）
├── .github/workflows/
│   ├── update-news.yml       # 30min 自动更新 + 部署
│   └── pages.yml             # (已禁用，避免双部署冲突)
├── docs/                     # 扩展文档
└── README.md                 # 本文件
```

## AI Agent 维护指南

想让 AI Agent（如 Claude Code / OpenClaw / Hermes）帮你维护本项目？直接说：

> "Use Scout Skill for AI News Radar. Ask me for my source list first, then decide whether each source should use RSS, public feeds, static pages, Jina fallback, AgentMail email, or be skipped. The goal is to deploy a serverless AI daily news site that updates automatically with GitHub Actions. Do not commit any API keys, cookies, tokens, or private email content into the repo."

Scout Skill 路径：`skills/ai-news-radar/SKILL.md`

## License

[MIT](LICENSE)
