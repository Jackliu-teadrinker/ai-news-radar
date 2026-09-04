# 🤖 AI News Radar — Humanoid Robot & Embodied AI News Radar

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green?style=flat-square)](https://jackliu-teadrinker.github.io/ai-news-radar/)
[![Actions](https://img.shields.io/badge/Actions-Running-blue?style=flat-square)](https://github.com/Jackliu-teadrinker/ai-news-radar/actions)
[![Self-Healing](https://img.shields.io/badge/Watchdog-Dual--Layer-orange?style=flat-square)](#dual-layer-self-healing-watchdog)

[中文版](README.md) · [Live Site](https://jackliu-teadrinker.github.io/ai-news-radar/)

---

## What Is This

A global news radar for **humanoid robots, embodied AI, brain-computer interfaces, and physical AI**.

Automatically collects, scores, deduplicates, and deploys the latest news every **30 minutes** via GitHub Actions, covering both Chinese and English sources with zero manual intervention.

**Page sections**:

| Section | Data File | Source |
|---------|-----------|--------|
| 📰 Robot Signal Feed | `latest-24h-min.json` | Google News (10 RSS groups) |
| 📱 WeChat Articles | `wechat-articles.json` | Curated + Exa MCP search |
| 🏛️ Policy | `government-news.json` | Government websites |
| 🎓 Academic | `arxiv-papers.json` | arXiv cs.RO |
| 🔗 Curated Anchors | `custom-anchors.json` | TechCrunch / IEEE / QbitAI etc. |

---

## How Data Gets Updated

Data production runs **entirely on GitHub's cloud** — no local machine involved:

```
update-news.yml (the only producer)
  ├─ schedule: every 30 minutes
  ├─ push: auto-deploy after source/code changes
  └─ workflow_dispatch: watchdog rescue / manual
         ↓
  fetch RSS → score / dedupe / time-window filter → commit → GitHub Pages deploy
```

---

## Dual-Layer Self-Healing Watchdog

GitHub Actions schedule has a platform-level **intermittent missed-fire** problem (delays from minutes to hours; observed 3 consecutive missed fires). Two independent watchdogs guard against "should-have-updated-but-didn't":

### Layer 1: Cloud keeper (`.github/workflows/keeper.yml`)

Runs on GitHub Actions — **on duty even when your local machine is off**. Every 20 minutes (at :07 / :27 / :47, staggered against the main task's :00/:30):

1. Checks Pages data age; stale if `generated_at` older than **45 minutes**
2. Confirms no queued/in-progress/recent (20 min) main-workflow runs (**anti-cascade**)
3. If stale and idle → dispatches the main workflow using the built-in `GITHUB_TOKEN`
4. Also re-enables both workflows, guarding against GitHub's "60-day inactivity auto-disable" trap

Permissions are only `contents: read` + `actions: write`. Zero external dependencies, no secrets required.

### Layer 2: Local watchdog (optional)

On duty whenever the local machine is on: a Hermes cron runs `radar_watchdog_v2.py` every 15 minutes, picks the fresher of two sources (local cache vs Pages), and dispatches the main workflow when stale (with a 25-minute cooldown). Backup for the cloud keeper.

### Expected Delay

| Scenario | Worst-case delay |
|---|---|
| Normal (schedule fires on time) | ≤ 30 minutes |
| Schedule missed fire, cloud keeper on duty (default) | ~20 minutes (detect + rescue) |
| Both watchdogs failed | Until next natural schedule fire (uncontrolled) |

> Note: watchdogs don't produce data — they are "supervisors" that kick the main workflow when it stalls. Pages is static hosting: when data goes stale the page still opens, just with older content. `generated_at` is the real freshness indicator.

---

## Quick Start

Visit: https://jackliu-teadrinker.github.io/ai-news-radar/

Run locally:

```bash
git clone https://github.com/Jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
```

---

## Modifying Sources

Edit `feeds/follow.example.opml` (main block) or `feeds/custom.opml` (curated anchors), then commit — deployment triggers automatically.

---

## Diagnostics

```bash
# Pages data freshness (cache-busted)
curl -s "https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json?cb=$(date +%s)" \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('generated_at'), d.get('total_items'), 'items')"

# Recent cloud keeper runs
gh run list -R Jackliu-teadrinker/ai-news-radar --workflow=keeper.yml --limit 5

# Recent main workflow runs
gh run list -R Jackliu-teadrinker/ai-news-radar --workflow=update-news.yml --limit 5
```

---

## Known Issues & Fix History

| Issue | Status |
|---|---|
| #26 Workflow concurrency races | ✅ Fixed 2026-08-27 (dedicated schedule concurrency group) |
| #31 GitHub cron intermittent missed fires | ✅ Mitigated by dual-layer watchdog (platform issue; worst case now ~20 min) |
| Local watchdog silent failure for 5 days | ✅ Fixed 2026-09-04 (zombie cache blocking freshness check + collector hang crash propagation) |
| #10 RSS silent 0 items | ⚠️ Open |
| #27 Google News mass 503 | ⚠️ Open (anti-cascade dispatch mitigates) |

---

## License

MIT
