# AI News Radar — Humanoid Robot Focus

## Scope

本仓库驱动人形机器人/具身智能专项新闻雷达：
- `scripts/update_news.py`：Python 采集脚本
- `feeds/follow.example.opml`：RSS 信源配置
- `.github/workflows/update-news.yml`：GitHub Actions 定时采集 + Pages 部署

## 工作规则

- 保持改动小、可审查
- 修改信源前先检查 `feeds/follow.example.opml`
- 不提交私有 OPML（使用 `feeds/follow.example.opml` 作为公开模板）
- 不提交 API key、Token、Cookie 或 `.env` 内容
- 优先使用公开 RSS/Atom/OPML 源，谨慎添加自定义爬虫

## 信源策略

人形机器人、具身智能、脑机接口、物理 AI 领域优先。
过滤：股票/ETF/扫地机器人/短快讯。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 本地运行采集
python scripts/update_news.py --output-dir data --window-hours 24

# 启动本地预览
python -m http.server 8080
# 打开 http://localhost:8080

# 手动触发 GitHub Actions
gh workflow run update-news.yml --repo Jackliu-teadrinker/ai-news-radar
```

## 项目结构

```
ai-news-radar/
├── feeds/follow.example.opml    # RSS 信源
├── scripts/update_news.py       # 采集脚本
├── data/*.json                 # 输出数据
└── .github/workflows/
    └── update-news.yml         # 自动更新
```
