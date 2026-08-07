# 🤖 AI News Radar — Humanoid Robot & Embodied AI News Radar

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/badge/Actions-Running-blue?style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions)
[![Update Frequency](https://img.shields.io/badge/Update-Every%2030min-purple?style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions)

[中文版](README.md) · [Live Site](https://jackliu-teadrinker.github.io/ai-news-radar/) · [Collaboration Guide](docs/radar-collaboration-guide.md)

---

## What Is This

A global news radar for **humanoid robots, embodied AI, brain-computer interfaces, and physical AI**.

Automatically collects, scores, deduplicates, and deploys the latest news every **30 minutes** via GitHub Actions, covering both Chinese and English sources with zero manual intervention.

**Page sections**:

| Section | Content |
|---------|---------|
| 📰 Main Feed | Full deduplicated news (CST 19:00 anchor + 24h window) |
| 📱 WeChat | Curated WeChat articles |
| 🏛️ Policy | Chinese government robotics/embodied AI policy news |
| 🎓 Academic | arXiv cs.RO papers |
| 🔗 Anchors | High-priority sites (TechCrunch / IEEE / 量子位, etc.) |

## Features

- **Auto-updates every 30 min**: GitHub Actions powered
- **Dual CN/EN sources**: 5 English + 5 Chinese Google News groups, clearly labeled 国外/国内
- **Bilingual titles**: English titles auto-translated to Chinese
- **Noise filtering**: stock tickers, ETFs, robot vacuums, short news filtered out
- **Five-dimension scoring**: relevance / authority / depth / timeliness / writing value
- **21-day archive dedup**: SHA1(title+url) global dedup
- **Self-healing watchdog**: auto-triggers workflow when data is stale >90min

## Quick Start

Visit the live site: <https://jackliu-teadrinker.github.io/ai-news-radar/>

Run locally:

```bash
git clone https://github.com/jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
```

Edit feeds in `feeds/follow.example.opml` (main) or `feeds/custom.opml` (anchors), commit, and auto-deploy.

## Project Layout

```
ai-news-radar/
├── feeds/                      # RSS source config (OPML)
├── scripts/                    # update_news / arxiv / government / curated / wechat
├── data/                       # Output JSON (served by Pages)
├── assets/                     # Frontend (index.html / app.js / styles.css)
├── docs/                       # Collaboration & postmortem docs
└── .github/workflows/
    └── update-news.yml         # 30-min auto update + deploy
```

## License

MIT
