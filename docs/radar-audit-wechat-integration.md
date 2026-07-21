# AI News Radar — 运行审计与微信板块集成方法论

> 本文档面向所有维护者（含 OpenClaw），说明雷达系统的运行逻辑、已知问题和微信板块的正确集成方式。

---

## 一、系统架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Actions                           │
│                      (update-news.yml)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. RSS 采集 (update_news.py)                                    │
│     ├── 解析 feeds/follow.example.opml (10 个 Google News RSS)   │
│     ├── 并发抓取 + 去重                                          │
│     ├── 噪声过滤 (ETF/扫地机/IPO 等)                             │
│     ├── 时间窗口过滤 (CST 19:00 anchor)                          │
│     ├── Google Translate 翻译英文标题                            │
│     ├── 五维评分 (relevance/authority/depth/timeliness/writing)  │
│     └── 输出:                                                     │
│         ├── data/latest-24h-min.json (top 500)                   │
│         ├── data/latest-24h-all.json (全部)                      │
│         └── data/source-status.json                              │
│                                                                 │
│  2. 精选 (curated_collector.py)                                  │
│     ├── 从 latest-24h-min.json 筛选 total_score >= 80            │
│     ├── 跨日 URL SHA1 去重                                       │
│     └── 输出: data/curated/YYYY-MM-DD.json (每天 ≤50 条)         │
│                                                                 │
│  3. 微信公众号 (wechat_collector.py) ← 当前未集成到 workflow     │
│     ├── 读取 data/wechat-manual.json (手动添加)                  │
│     ├── 读取 data/wechat-articles.json (旧格式兼容)              │
│     ├── 尝试抓取微信文章发布时间                                 │
│     └── 标准化输出为雷达统一格式                                 │
│                                                                 │
│  4. 版本更新 + 推送                                              │
│     ├── update-index-version.py → 更新 index.html 版本号         │
│     └── Auto-push data → git add data/ scripts/feeds/ index.html│
│         → commit → git push origin master                        │
│                                                                 │
│  5. GitHub Pages 部署                                            │
│     ├── upload-pages-artifact                                   │
│     └── deploy-pages                                           │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     前端 (app.js + index.html)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  loadNewsData() → fetch ./data/latest-24h-min.json              │
│    ├── payload.items_ai → 主列表 (机器人强相关)                  │
│    ├── payload.items_all → 全量模式                              │
│    └── payload.site_stats → 站点统计                             │
│                                                                 │
│  loadWechatArticles() → fetch ./data/wechat-articles.json       │
│    └── 渲染独立 "微信公众号" 专区                                │
│                                                                 │
│  每 30 秒轮询 wechat 专区更新                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、数据流与文件格式

### 2.1 核心数据文件

| 文件 | 用途 | 是否 Git 跟踪 | 说明 |
|------|------|-------------|------|
| `data/latest-24h-min.json` | 主数据源（top 500） | ✅ | 前端 `loadNewsData()` 读取 |
| `data/latest-24h-all.json` | 全量数据 | ✅ | 前端 "全量模式" 读取 |
| `data/source-status.json` | 源健康状态 | ✅ | 前端 "源状态" 面板 |
| `data/curated/YYYY-MM-DD.json` | 每日精选 | ✅ | 独立存档 |
| `data/wechat-articles.json` | 微信公众号文章 | ✅ | 前端 `loadWechatArticles()` 读取 |
| `data/wechat-manual.json` | 手动添加的微信文章 | ✅ | wechat_collector 的输入源 |
| `data/latest-24h.json` | 旧格式（已弃用） | ❌ (.gitignore) | 不再使用 |

### 2.2 数据格式

**最新格式** (`latest-24h-min.json`):
```json
{
  "generated_at": "2026-07-21T05:10:11.074680+00:00",
  "total_items": 281,
  "items_ai": [...],        // 主列表
  "items_all": [...],       // 全量列表
  "items_all_raw": [...],   // 原始列表（未过滤）
  "site_stats": [...],
  "total_items_raw": 864,
  "total_items_all_mode": 281
}
```

**微信文章格式** (`wechat-articles.json`):
```json
{
  "articles": [...],
  "total_articles": 0,
  "last_updated": "2026-07-21T05:10:11.074680+00:00",
  "source": "auto_filtered_by_time_window"
}
```

**手动微信文章** (`wechat-manual.json`):
```json
{
  "articles": [
    {
      "url": "https://mp.weixin.qq.com/s/...",
      "title": "文章标题",
      "source": "公众号名称",
      "published_at": "2026-07-16T20:16:00+08:00",
      "collected": true,
      "added_by": "jack-manual"
    }
  ],
  "total_articles": 10
}
```

---

## 三、已知问题与风险

### 3.1 🔴 严重：微信板块未集成到 Workflow

**问题**: `wechat_collector.py` 存在于 `scripts/` 目录，但 **`update-news.yml` 中没有任何步骤调用它**。

**后果**:
- `data/wechat-articles.json` 始终为空（`articles: []`）
- 前端 "微信公众号" 专区显示 "暂无微信公众号文章"
- `data/wechat-manual.json` 中的 10 篇文章从未被处理

**根因**: 微信板块是独立开发的，但未纳入 CI/CD pipeline。

### 3.2 🟡 中等：多个微信采集器共存

仓库中有三个微信采集脚本：
- `scripts/wechat-collector.py` — 旧版（Exa MCP 搜索）
- `scripts/wechat-collector-v2.py` — 中间版（含 relevance 关键词过滤）
- `scripts/wechat_collector.py` — 当前版（仅加载手动文章）

**建议**: 保留 `wechat_collector.py` 作为主版本，删除或标记废弃另外两个。

### 3.3 🟢 轻微：`gh_auto_push_data.py` 已不存在

- 文件已从仓库移除（commit `93aac2df`）
- 取而代之的是 workflow 中内联的 `Auto-push data` 步骤
- 该步骤直接 `git add data/` 推送所有数据文件

### 3.4 🟡 潜在：`wechat-manual.json` 中有临时占位符

```json
{
  "url": "https://mp.weixin.qq.com/s/TEMP_PLACEHOLDER",
  "title": "机器人奇妙夜落地贵阳..."
}
```

这个 `TEMP_PLACEHOLDER` URL 会被 `wechat_collector.py` 处理，可能导致异常。

---

## 四、微信板块集成方法论

### 4.1 设计理念

微信板块与 RSS 板块 **并行运行，互不干扰**：

```
RSS 板块 (update_news.py)          微信板块 (wechat_collector.py)
     │                                   │
     ▼                                   ▼
Google News RSS              wechat-manual.json (手动添加)
arXiv RSS                    wechat-articles.json (旧格式兼容)
TechCrunch RSS               微信手机UA抓取 (预留)
36氪 RSS                     Exa MCP 搜索 (预留)
     │                                   │
     ▼                                   ▼
latest-24h-*.json          wechat-articles.json
     │                                   │
     ▼                                   ▼
         app.js (前端) 分别渲染两个专区
```

### 4.2 正确集成方式

**方案 A：在 workflow 中添加微信采集步骤**

在 `update-news.yml` 中，`Curate high-quality articles` 步骤之后添加：

```yaml
      - name: Collect WeChat articles
        env:
          TZ: Asia/Shanghai
        run: python scripts/wechat_collector.py

      - name: Collect WeChat articles (v2 - Exa MCP)
        env:
          TZ: Asia/Shanghai
        run: python scripts/wechat-collector-v2.py
```

**方案 B：独立 workflow**

创建 `.github/workflows/wechat-collect.yml`，独立调度微信采集：

```yaml
name: WeChat Article Collector
on:
  schedule:
    - cron: "0 1 * * *"  # 每天北京时间 9:00
    - cron: "0 13 * * *" # 每天北京时间 21:00
  workflow_dispatch:

jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - name: Run WeChat collector
        run: python scripts/wechat_collector.py --all
      - name: Push WeChat data
        run: |
          git config user.email "radar-bot@users.noreply.github.com"
          git config user.name "radar-bot"
          git add data/wechat-articles.json data/wechat-manual.json
          git commit -m "[wechat] article collection $(date -u +%Y-%m-%dT%H:%M:%SZ)" || echo "no changes"
          git push origin master || echo "push failed"
```

### 4.3 数据格式标准化

wechat_collector.py 输出的文章应与 RSS 文章格式一致：

```python
{
    'id': hashlib.sha1(url.encode()).hexdigest()[:32],
    'title': '文章标题',
    'title_zh': '',  # 微信文章默认中文
    'url': '原文链接',
    'published_at': 'ISO 时间 (UTC)',
    'category': '微信公众号',
    'gn_label': 'wechat',
    'site_name': '公众号名称',
    'source': '微信公众号',
    'site_id': 'wechat',
    'description': '摘要/笔记',
    'ai_score': 90,  # 手动添加的文章默认高分
    'ai_label': '高价值',
    'relevance': 0.9,
    'authority': 0.8,
    'depth': 0.85,
    'timeliness': 1.0,
    'total_score': 90,
}
```

### 4.4 微信公众号文章采集 SOP

#### 4.4.1 手动添加（主要方式）

1. 编辑 `data/wechat-manual.json`
2. 添加文章条目：
```json
{
  "url": "https://mp.weixin.qq.com/s/xxxxxx",
  "title": "文章标题",
  "source": "公众号名称",
  "published_at": "2026-07-16T20:16:00+08:00",
  "collected": true,
  "added_by": "jack-manual"
}
```
3. 提交并推送

#### 4.4.2 微信手机UA抓取（备用）

当 `wechat-collector.py` 启用 Exa MCP 搜索时：
1. 搜索关键词：`site:mp.weixin.qq.com 具身智能`
2. 对每个结果调用 `wechat-fetch.py`（微信手机UA绕过验证码）
3. 抓取正文，过滤无关内容
4. 标准化输出

#### 4.4.3 注意事项

- **微信公众号 URL 格式**: `https://mp.weixin.qq.com/s/xxxxxxxxx`
- **发布时间**: 微信文章时间通常在 HTML 中以 `YYYY-MM-DD HH:MM` 格式出现
- **验证码**: 微信有反爬机制，需要使用手机 UA 或 Cookie
- **频率限制**: 建议每 30 秒请求一次，避免被封

---

## 五、维护清单

### 5.1 日常维护
- [ ] 检查 `data/wechat-manual.json` 是否有 `TEMP_PLACEHOLDER` 等占位符
- [ ] 确认 `wechat-articles.json` 有数据（非空）
- [ ] 检查 `source-status.json` 中 10/10 feeds OK

### 5.2 定期维护
- [ ] 清理 `scripts/wechat-collector.py` 和 `wechat-collector-v2.py`（标记废弃）
- [ ] 审查 `curated/` 目录，删除过时文件
- [ ] 检查 `data/` 中是否有重复存储

### 5.3 故障排查
1. **网站无数据**: 检查 `latest-24h-min.json` 的 `generated_at` 和 `items_ai` 长度
2. **微信专区空白**: 检查 `wechat-articles.json` 是否为空，`wechat-manual.json` 是否有数据
3. **Workflow 失败**: 检查 GitHub Actions 日志，重点关注 `update_news.py` 的 `NameError`

---

## 六、与 OpenClaw 协作指南

### 6.1 分工建议

| 模块 | 负责人 | 说明 |
|------|--------|------|
| RSS 采集 + 评分 | OpenClaw | Google News/arXiv/TechCrunch/36氪 |
| 微信采集 | Jack | 微信生态（手动添加 + 抓取） |
| 前端展示 | 双方协商 | app.js 的渲染逻辑 |
| 精选算法 | OpenClaw | curated_collector.py |
| 基础设施 | 双方协商 | workflow, deployment |

### 6.2 数据隔离原则

- **RSS 板块**: 输出到 `latest-24h-*.json`，由 `update_news.py` 生成
- **微信板块**: 输出到 `wechat-articles.json`，由 `wechat_collector.py` 生成
- **两者不交叉**：微信文章不进入 RSS 评分系统，RSS 文章不进入微信专区

### 6.3 提交规范

```
[rss] 更新 Google News 关键词
[wechat] 添加手动微信文章
[curate] 调整精选阈值
[fix] 修复 xxx bug
[docs] 更新文档
```

### 6.4 冲突预防

1. **不要同时修改同一个数据文件**：RSS 写 `latest-24h-*`，微信写 `wechat-*`
2. **workflow 步骤顺序固定**：RSS 采集 → 精选 → 微信采集 → 版本更新 → 推送
3. **前端兼容性**：任何数据格式变更需要同步更新 `app.js`

---

## 七、快速参考

### 7.1 关键文件路径

```
.github/workflows/update-news.yml    # 主 workflow
scripts/update_news.py               # RSS 采集 + 评分
scripts/curated_collector.py         # 精选算法
scripts/wechat_collector.py          # 微信采集
assets/app.js                        # 前端逻辑
data/wechat-manual.json              # 手动微信文章
data/wechat-articles.json            # 微信文章输出
```

### 7.2 常用命令

```bash
# 本地测试 RSS 采集
python scripts/update_news.py --output-dir ./test-data

# 本地测试微信采集
python scripts/wechat_collector.py

# 本地测试精选
python scripts/curated_collector.py --data-path ./test-data/latest-24h-min.json

# 查看源状态
cat data/source-status.json | jq '.summary'
```

### 7.3 环境变量

```bash
TZ=Asia/Shanghai          # 时区（workflow 中设置）
GITHUB_TOKEN              # GitHub API 令牌（workflow 中设置）
```

---

## 八、版本历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-14 | v1.0 | 修复 ANCHOR_HOUR 缺失 bug |
| 2026-07-14 | v1.1 | 修复 index.html 版本号不更新 bug |
| 2026-07-21 | v1.2 | 审计文档创建，明确微信板块集成方案 |

---

*本文档由 Jack 创建，供所有维护者参考。如有疑问请联系 jackliu-teadrinker@gmail.com*
