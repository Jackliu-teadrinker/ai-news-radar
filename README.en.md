# Humanoid Robot News Radar

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/github/actions/workflow/status/Jackliu-teadrinker/ai-news-radar/update-news.yml?branch=master&label=update&style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions/workflows/update-news.yml)

[Live Site](https://jackliu-teadrinker.github.io/ai-news-radar/)

---

## What Is This

A **humanoid robot / embodied AI news radar** that automatically tracks the latest developments in humanoid robotics, embodied intelligence, brain-computer interfaces (BCI), and Physical AI worldwide.

The radar updates every 30 minutes during 09:00-20:00 CST, covering news from the previous day's 9AM to the present.

## Features

- **30-minute auto-update**: Powered by GitHub Actions, zero maintenance required
- **Bilingual titles**: English articles auto-translated to Chinese
- **Industry-specific filtering**: Filters out stock/ETF news, robot vacuum noise, and short bulletins
- **Relevance scoring**: Prioritizes high-value industry articles
- **Multi-source coverage**: Google News EN ×5 + CN ×5 + TechCrunch + 36kr
- **21-day archive with dedup**: SHA1(title+url) dedup across full archive

## Covered Areas

| Category | Sources |
|----------|---------|
| Humanoid Robot | GN: humanoid robot / 国外人形机器人资讯 |
| Embodied AI | GN: embodied intelligence / GN: 具身智能 |
| BCI | GN: BCI / GN: 脑机接口 |
| Physical AI | GN: Physical AI / GN: 物理AI |
| Robotics | GN: robot / 国外机器人资讯 |
| Industry Media | TechCrunch, 36kr |

## Quick Start

Live site: [https://jackliu-teadrinker.github.io/ai-news-radar/](https://jackliu-teadrinker.github.io/ai-news-radar/)

Local run:

```bash
git clone https://github.com/jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
# Open http://localhost:8080
```

## GitHub Actions

`.github/workflows/update-news.yml`:

- cron: `*/30 * * * *`
- push trigger
- `workflow_dispatch` for manual trigger
- Auto-commit data + Pages deployment

## License

[MIT](../LICENSE)
