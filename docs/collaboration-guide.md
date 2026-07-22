# AI News Radar — 协作指南

> 本文档说明 Jack（Hermes Agent）和 OpenClaw 在雷达项目中的分工、协作方式和数据流。

---

## 一、项目概述

AI News Radar 是一个人形机器人/具身智能领域的新闻聚合平台，运行在 GitHub Pages 上。

**数据来源**：
- Google News RSS（10 个关键词源）
- arXiv 预印本（Robotics/Embodied AI）
- TechCrunch Robotics
- 36氪
- 微信公众号（手动添加）

**核心指标**：
- 每天采集 ~800-1000 条原始文章
- 过滤后保留 ~200-300 条高质量内容
- 精选 top 50 条每日存档

---

## 二、角色分工

### Jack（Hermes Agent）

**职责**：
- 微信板块的维护和更新
- 手动添加微信公众号文章到 `data/wechat-manual.json`
- 运行 `wechat-collector-v2.py` 处理微信文章
- 文档维护（审计、方法论、协作指南）
- 前端展示优化（app.js 渲染逻辑）

**不负责的模块**：
- RSS 采集和评分（OpenClaw 负责）
- 精选算法（OpenClaw 负责）
- GitHub Actions workflow 配置（双方协商）

**日常工作**：
```bash
# 1. 手动添加微信文章
# 编辑 data/wechat-manual.json，添加新文章

# 2. 本地测试微信采集
python scripts/wechat-collector-v2.py --manual --output data/wechat-articles.json

# 3. 提交微信相关更改
git add data/wechat-manual.json data/wechat-articles.json
git commit -m "[wechat] 添加/更新微信文章"
git push origin master
```

### OpenClaw

**职责**：
- RSS 采集和评分（`update_news.py`）
- 精选算法（`curated_collector.py`）
- GitHub Actions workflow 配置和维护
- 数据管道自动化（schedule/push/commit/push）
- 源健康监控（`source-status.json`）
- 噪声过滤规则维护

**不负责的模块**：
- 微信板块（Jack 负责）
- 手动微信文章添加

**日常工作**：
```bash
# 1. 运行 RSS 采集
python scripts/update_news.py --output-dir data --window-hours 24

# 2. 运行精选
python scripts/curated_collector.py --data-path data/latest-24h-min.json

# 3. 检查源状态
cat data/source-status.json | jq '.summary'

# 4. 提交数据更改
git add data/ scripts/feeds/ index.html
git commit -m "[rss] data refresh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin master
```

---

## 三、数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                     GitHub Actions (update-news.yml)            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1: RSS 采集 (OpenClaw 负责)                                │
│    python scripts/update_news.py --output-dir data              │
│    → 输出: data/latest-24h-min.json                             │
│    → 输出: data/latest-24h-all.json                             │
│    → 输出: data/source-status.json                              │
│                                                                 │
│  Step 2: 精选 (OpenClaw 负责)                                    │
│    python scripts/curated_collector.py --data-path              │
│      data/latest-24h-min.json --curated-dir data/curated        │
│    → 输出: data/curated/YYYY-MM-DD.json                         │
│                                                                 │
│  Step 3: 微信采集 (Jack 负责)                                    │
│    python scripts/wechat-collector-v2.py --manual               │
│      --output data/wechat-articles.json                         │
│    → 输出: data/wechat-articles.json                            │
│                                                                 │
│  Step 4: 版本更新 + 推送 (双方协商)                              │
│    python -c "..." # 更新 index.html 版本号                      │
│    git add data/ scripts/feeds/ index.html                      │
│    git commit -m "[radar-auto] data refresh ..."                │
│    git push origin master                                        │
│                                                                 │
│  Step 5: GitHub Pages 部署                                       │
│    upload-pages-artifact + deploy-pages                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     前端 (app.js)                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  RSS 板块:                                                      │
│    loadNewsData() → latest-24h-min.json                         │
│    ├── items_ai → 主列表 (281 条)                               │
│    ├── items_all → 全量模式                                     │
│    └── site_stats → 站点统计                                    │
│                                                                 │
│  微信板块:                                                      │
│    loadWechatArticles() → wechat-articles.json                  │
│    └── 渲染独立 "微信公众号" 专区                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 四、协作规则

### 4.1 数据隔离

**RSS 板块** 和 **微信板块** 完全隔离：

| 板块 | 数据文件 | 写入方 | 读取方 |
|------|---------|--------|--------|
| RSS | `latest-24h-*.json` | OpenClaw | 前端 |
| RSS | `source-status.json` | OpenClaw | 前端 |
| RSS | `curated/YYYY-MM-DD.json` | OpenClaw | 存档 |
| 微信 | `wechat-articles.json` | Jack | 前端 |
| 微信 | `wechat-manual.json` | Jack | wechat-collector |

**禁止行为**：
- ❌ OpenClaw 修改 `wechat-articles.json` 或 `wechat-manual.json`
- ❌ Jack 修改 `latest-24h-*.json` 或 `source-status.json`
- ❌ 微信文章混入 RSS 评分系统
- ❌ RSS 文章混入微信专区

### 4.2 提交规范

**Jack 的提交**：
```
[wechat] 添加手动微信文章: xxx
[wechat] 清理微信文章占位符
[docs] 更新协作指南
[fix] 修复微信采集 bug
```

**OpenClaw 的提交**：
```
[rss] 更新 Google News 关键词
[rss] 调整噪声过滤规则
[curate] 调整精选阈值
[fix] 修复 RSS 采集 bug
[infra] 更新 workflow 配置
```

### 4.3 冲突预防

1. **不同数据文件**：RSS 和微信使用不同的文件，不会冲突
2. **workflow 步骤顺序**：RSS 采集 → 精选 → 微信采集 → 推送
3. **前端兼容性**：任何数据格式变更需要同步更新 `app.js`
4. **沟通渠道**：重大变更前在 issue 或 PR 中讨论

### 4.4 联合维护

以下文件需要双方协商修改：
- `.github/workflows/update-news.yml` — workflow 配置
- `assets/app.js` — 前端渲染逻辑
- `index.html` — 页面结构和版本
- `feeds/*.opml` — RSS 源配置

---

## 五、故障排查

### 5.1 网站无数据

**症状**：打开 https://jackliu-teadrinker.github.io/ai-news-radar/ 显示空白

**排查步骤**：
1. 检查 `data/latest-24h-min.json` 的 `generated_at` 是否最新
2. 检查 `items_ai` 数组是否有数据
3. 检查 GitHub Actions 日志是否有失败
4. 检查 `source-status.json` 中 10/10 feeds 是否 OK

**常见原因**：
- `update_news.py` 报错（如 ANCHOR_HOUR 未定义）
- Google News RSS 被屏蔽
- GitHub Actions 配额耗尽

### 5.2 微信专区空白

**症状**：微信专区显示 "暂无微信公众号文章"

**排查步骤**：
1. 检查 `data/wechat-articles.json` 是否有数据
2. 检查 `data/wechat-manual.json` 是否有文章
3. 检查 `wechat-collector-v2.py` 是否被 workflow 调用
4. 检查 `wechat-collector-v2.py` 的 `--manual` 参数是否正确

**常见原因**：
- workflow 中没有调用微信采集步骤
- `wechat-manual.json` 为空或格式错误
- `wechat-collector-v2.py` 路径错误

### 5.3 数据更新延迟

**症状**：数据超过 24 小时未更新

**排查步骤**：
1. 检查 GitHub Actions 的 schedule 是否触发
2. 检查 `concurrency` 配置是否导致任务取消
3. 检查 `timeout-minutes` 是否不足
4. 检查 GitHub Pages 缓存（Ctrl+Shift+R 强制刷新）

---

## 六、常见问题

### Q: 微信文章为什么不进入 RSS 评分？

A: 微信文章是独立板块，由 Jack 手动添加，不经过 RSS 采集和评分流程。这样可以保持微信内容的独立性和可控性。

### Q: 为什么有三个微信采集器？

A: 历史遗留。最初开发了 `wechat-collector.py`（449行），后来精简为 `wechat-collector-v2.py`（281行），又有一个最简版 `wechat_collector.py`（173行）。推荐只保留 v2 版本，删除另外两个。

### Q: 微信板块能自动搜索吗？

A: 可以。`wechat-collector-v2.py` 支持 Exa MCP 搜索，但在 GitHub Actions 环境中可能受限。建议在本地运行搜索，只将结果提交到 `wechat-manual.json`。

### Q: OpenClaw 能修改微信相关代码吗？

A: 不建议。微信板块是 Jack 的专属领域，OpenClaw 应该专注于 RSS 采集和评分。如果有微信相关的 bug，应该报告给 Jack 修复。

### Q: Jack 能修改 RSS 相关代码吗？

A: 不建议。RSS 采集和评分是 OpenClaw 的专属领域，Jack 应该专注于微信板块。如果有 RSS 相关的 bug，应该报告给 OpenClaw 修复。

---

## 七、快速参考

### 7.1 关键文件

```
.github/workflows/update-news.yml    # 主 workflow (双方协商)
scripts/update_news.py               # RSS 采集 (OpenClaw)
scripts/curated_collector.py         # 精选 (OpenClaw)
scripts/wechat-collector-v2.py       # 微信采集 (Jack)
assets/app.js                        # 前端 (双方协商)
data/latest-24h-min.json             # RSS 数据 (OpenClaw)
data/wechat-articles.json            # 微信数据 (Jack)
data/wechat-manual.json              # 手动微信文章 (Jack)
```

### 7.2 常用命令

**OpenClaw**：
```bash
# RSS 采集
python scripts/update_news.py --output-dir data

# 精选
python scripts/curated_collector.py --data-path data/latest-24h-min.json

# 检查源状态
cat data/source-status.json | jq '.summary'
```

**Jack**：
```bash
# 微信采集
python scripts/wechat-collector-v2.py --manual --output data/wechat-articles.json

# 微信采集 + Exa MCP 搜索（本地）
python scripts/wechat-collector-v2.py --search "具身智能" --output data/wechat-articles.json
```

### 7.3 联系方式

- **Jack**: jackliu-teadrinker@gmail.com
- **OpenClaw**: 通过 GitHub Issues 沟通

---

*本文档已合并到 `docs/radar-collaboration-guide.md`，请以该文件为准。本文件保留作为历史参考。*

*本文档由 Jack 创建，供所有维护者参考。如有更新请通知双方。*
