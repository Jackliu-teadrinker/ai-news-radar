# AI News Radar — 协作指南

> 雷达项目由两个 Agent 协同维护：OpenClaw（RSS 雷达）和 Hermes Agent（微信公众号）。修改前先读本指南，确认边界后再行动。

---

## 一、项目架构

```
GitHub Actions (每30分钟自动执行)
       │
       ├── Step 1: RSS 采集 (OpenClaw)
       │     scripts/update_news.py
       │     → data/latest-24h-min.json  (281条精选)
       │     → data/latest-24h-all.json  (全量)
       │     → data/source-status.json   (源健康状态)
       │
       ├── Step 2: 精选存档 (OpenClaw)
       │     scripts/curated_collector.py
       │     → data/curated/YYYY-MM-DD.json  (每日top50)
       │
       ├── Step 3: 微信采集 (Hermes)
       │     scripts/wechat-collector-v2.py
       │     → data/wechat-articles.json
       │     → data/wechat-manual.json
       │
       ├── Step 4: 版本更新 + 推送 (OpenClaw)
       │     更新 index.html 版本哈希
       │     git commit + push
       │
       └── Step 5: GitHub Pages 部署
             → https://jackliu-teadrinker.github.io/ai-news-radar/
```

---

## 二、角色分工

### OpenClaw — RSS 雷达专属

**职责**：
- `scripts/update_news.py` — RSS 采集、评分、过滤
- `scripts/curated_collector.py` — 精选算法
- `scripts/ai_relevance.py` — 相关性评分
- `.github/workflows/update-news.yml` — GitHub Actions 维护
- `feeds/*.opml` — RSS 信源配置
- 数据管道自动化（刷新→版本更新→推送→部署）

**不越界**：不碰微信相关文章和代码。

---

### Hermes Agent — 微信公众号专属

**职责**：
- `data/wechat-manual.json` — 手动添加微信文章
- `scripts/wechat-collector-v2.py` — 微信采集器
- `data/wechat-articles.json` — 微信数据
- 微信专区前端展示逻辑

**不越界**：不动 RSS 核心数据和评分代码。

---

### 联合维护（需双方协商）

| 文件 | 说明 |
|------|------|
| `assets/app.js` | 前端渲染逻辑 |
| `index.html` | 页面结构和版本哈希 |
| `feeds/follow.example.opml` | RSS 信源配置 |

---

## 三、数据隔离规则

| 板块 | 文件 | 写入方 | 读取方 |
|------|------|--------|--------|
| RSS | `latest-24h-*.json` | OpenClaw | 前端 |
| RSS | `source-status.json` | OpenClaw | 前端 |
| RSS | `curated/YYYY-MM-DD.json` | OpenClaw | 存档 |
| 微信 | `wechat-articles.json` | Hermes | 前端 |
| 微信 | `wechat-manual.json` | Hermes | 采集器 |

**禁止行为**：
- ❌ OpenClaw 修改微信相关文件
- ❌ Hermes 修改 RSS 核心数据文件
- ❌ 微信文章混入 RSS 评分
- ❌ RSS 文章混入微信专区

---

## 四、修改前必读规则

> 修改任何文件前，先读本指南确认边界。

1. **OpenClaw 修改前**：读 `docs/collaboration-guide.md` 确认不碰微信模块
2. **Hermes 修改前**：读本指南确认不碰 RSS 核心代码
3. **共同文件**（`app.js`、`index.html`、`update-news.yml`）：先知会对方，再动手

---

## 五、提交规范

**OpenClaw**：
```
[rss] 更新关键词 / 调整噪声过滤
[curate] 调整精选阈值
[fix] 修复采集bug
[infra] 更新workflow配置
[data] 数据刷新
[docs] 更新文档
```

**Hermes**：
```
[wechat] 添加/更新微信文章
[wechat] 清理占位符
[docs] 更新协作指南
[fix] 修复微信采集bug
```

---

## 六、故障排查

### 网站无数据（RSS 问题）
1. 检查 `latest-24h-min.json` 的 `generated_at` 是否最新
2. 检查 `items_ai` 数组是否有数据
3. 查看 GitHub Actions 运行日志
4. 检查 `source-status.json` 中 feeds 状态

### 微信专区空白（Hermes 问题）
1. 检查 `wechat-articles.json` 是否有数据
2. 检查 `wechat-manual.json` 是否有文章
3. 检查 `wechat-collector-v2.py` 是否正常

### 数据延迟
1. 检查 GitHub Actions schedule 是否触发
2. 检查 `concurrency` 配置是否导致任务被取消
3. Ctrl+Shift+R 强制刷新浏览器

---

## 七、关键文件索引

```
# OpenClaw 专属
scripts/update_news.py               # RSS采集
scripts/curated_collector.py         # 精选
scripts/ai_relevance.py              # 评分
.github/workflows/update-news.yml    # Workflow
feeds/follow.example.opml            # 信源配置
data/latest-24h-min.json             # 精选数据
data/source-status.json              # 源状态

# Hermes 专属
scripts/wechat-collector-v2.py       # 微信采集
data/wechat-articles.json            # 微信数据
data/wechat-manual.json              # 手动文章

# 共同维护
assets/app.js                        # 前端渲染
index.html                          # 页面结构
docs/radar-collaboration-guide.md   # 本文件
```

---

## 八、常用命令

**OpenClaw**：
```bash
# RSS采集
python scripts/update_news.py --output-dir data --window-hours 24

# 精选
python scripts/curated_collector.py --data-path data/latest-24h-min.json

# 检查源状态
cat data/source-status.json | jq '.summary'
```

**Hermes**：
```bash
# 微信采集（本地）
python scripts/wechat-collector-v2.py --manual --output data/wechat-articles.json

# 微信采集+搜索
python scripts/wechat-collector-v2.py --search "具身智能" --output data/wechat-articles.json
```

---

*本指南由 OpenClaw 和 Hermes Agent 共同维护，修改前请确认边界。*
