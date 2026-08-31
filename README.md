# 🤖 AI News Radar

[GitHub Pages](https://jackliu-teadrinker.github.io/ai-news-radar/) · [English](README.en.md)

---

## 这是什么

人形机器人 / 具身智能 / 脑机接口 / 物理 AI 领域的全球新闻雷达。每 30 分钟由 GitHub Actions 自动采集、评分、去重并部署，覆盖国内外中英文信源。

**页面板块：**

| 板块 | 数据文件 | 来源 |
|------|----------|------|
| 📰 机器人信号流 | `latest-24h-all.json` | Google News 10 组 RSS |
| 📱 微信公众号 | `wechat-articles.json` | 手动维护 + Exa MCP 搜索 |
| 🏛️ 政策专区 | `government-news.json` | 政府官网 |
| 🎓 学术专区 | `arxiv-papers.json` | arXiv cs.RO |
| 🔗 精选锚点 | `custom-anchors.json` | TechCrunch/IEEE/量子位等 |

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

## 架构

```
feeds/follow.example.opml (Google News 10 组)
         ↓
GitHub Actions (每 30min)
         ↓
update_news.py → 评分/去重/时间窗口过滤
         ↓
data/*.json → GitHub Pages 部署
```

---

## 修改信源

编辑 `feeds/follow.example.opml`（主区块）或 `feeds/custom.opml`（锚点专区），commit 后自动触发部署。

---

## 健康监控

- **Hermes watchdog**（`radar_freshness_watchdog.py`）：每 15 分钟检查 Pages 数据新鲜度
- **Pre-flight checks**：每次 workflow 运行前验证语法、类型、时间窗口逻辑
- **Auto-recovery**：数据 stale >60min 时自动触发 workflow dispatch

---

## License

MIT
