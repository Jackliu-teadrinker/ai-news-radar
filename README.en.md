# Humanoid Robot News Radar

[中文版](README.md) · [在线站点](https://jackliu-teadrinker.github.io/ai-news-radar/)

---

## What Is This

A global news radar for **humanoid robots, embodied AI, brain-computer interfaces, and physical AI**.

Automatically tracks the latest developments in humanoid robotics, embodied intelligence, BCI, and physical AI every 30 minutes via GitHub Actions, covering content from the past 24 hours.

## Features

- **Auto-updates every 30 min**: GitHub Actions powered, zero manual intervention
- **Multi-source coverage**: Google News (EN/CN), RSSHub (Baidu/WeChat), arXiv papers
- **Industry-specific filtering**: Filters out stock tickers, ETFs, robot vacuums, and spam
- **Relevance scoring**: Important articles ranked by domain relevance
- **Deduplication**: SHA1-based global dedup across 21-day archive
- **Health monitoring**: Independent watchdog detects stale data and alerts

## Coverage Domains

| Domain | Sources |
|--------|---------|
| Humanoid Robots | GN: humanoid robot / 国外人形机器人资讯 |
| Embodied AI | GN: embodied intelligence / GN: 具身智能 |
| Brain-Computer Interface | GN: BCI / GN: 脑机接口 |
| Physical AI | GN: Physical AI / GN: 物理AI |
| Robotics | GN: robot / 国外机器人资讯 |
| Industry Media | TechCrunch, 36kr |

## Quick Start

Visit: [https://jackliu-teadrinker.github.io/ai-news-radar/](https://jackliu-teadrinker.github.io/ai-news-radar/)

Run locally:

```bash
git clone https://github.com/jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
# Open http://localhost:8080
```

## Data Output

```
data/
├── latest-24h-min.json   # Curated view (Relevance > 0.4, ≤50 items)
├── latest-24h-all.json   # Full view (all deduplicated items)
├── source-status.json    # Source health status
└── archive.json          # 21-day archive
```

## License

[MIT](LICENSE)
