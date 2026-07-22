# AI News Radar — OpenClaw 协作指南

> 本文档说明 OpenClaw（Agnes-2.5-Flash）在雷达项目中的职责、操作边界和协作规则。

---

## 一、OpenClaw 的核心职责

### ✅ 负责模块

| 模块 | 具体任务 | 相关文件 |
|------|---------|---------|
| **RSS 采集** | 运行 `update_news.py`，维护信源配置 | `scripts/update_news.py`, `feeds/*.opml` |
| **评分系统** | 维护评分算法、噪声过滤规则 | `scripts/ai_relevance.py` |
| **精选流程** | 运行 `curated_collector.py`，调整阈值 | `scripts/curated_collector.py` |
| **Workflow 配置** | 维护 GitHub Actions 定时任务 | `.github/workflows/update-news.yml` |
| **数据管道** | 确保数据自动刷新、版本更新、推送 | 整个 pipeline |
| **源健康监控** | 检查 feeds 状态、故障排查 | `data/source-status.json` |
| **前端兼容性** | 确保 RSS 板块正常渲染 | `assets/app.js`（RSS 部分） |

### ❌ 不负责模块

| 模块 | 负责人 | 说明 |
|------|--------|------|
| **微信公众号文章** | Hermes Agent | 微信板块由 Hermes 专属维护 |
| **手动微信文章添加** | Hermes Agent | `data/wechat-manual.json` 由 Hermes 编辑 |
| **微信采集器** | Hermes Agent | `wechat-collector-v2.py` 由 Hermes 维护 |
| **微信专区前端** | Hermes Agent | 微信展示逻辑由 Hermes 负责 |

---

## 二、OpenClaw 的日常操作

### 2.1 每日自动化流程

```bash
# GitHub Actions 自动执行（每 30 分钟）
# 1. update_news.py → 采集 + 评分 + 过滤
# 2. curated_collector.py → 精选 top 50
# 3. 更新 index.html 版本哈希
# 4. git commit + push
# 5. GitHub Pages 部署
```

### 2.2 本地调试命令

```bash
# 手动运行 RSS 采集
python scripts/update_news.py --output-dir data --window-hours 24

# 手动运行精选
python scripts/curated_collector.py --data-path data/latest-24h-min.json --curated-dir data/curated

# 检查源状态
cat data/source-status.json | jq '.summary'

# 验证 JSON 结构
python -c "import json; d=json.load(open('data/latest-24h-min.json')); print(d.keys())"
```

### 2.3 故障排查

**网站无数据**：
1. 检查 `data/latest-24h-min.json` 的 `generated_at` 是否最新
2. 检查 `items_ai` 数组是否有数据
3. 检查 GitHub Actions 日志
4. 检查 `source-status.json` 中 feeds 状态

**数据更新延迟**：
1. 检查 cron schedule 是否正常触发
2. 检查 `concurrency.cancel-in-progress` 是否导致任务取消
3. 检查 `timeout-minutes` 是否不足
4. 强制刷新浏览器（Ctrl+Shift+R）

---

## 三、数据隔离规则

### 3.1 RSS 板块（OpenClaw）

| 文件 | 写入方 | 读取方 |
|------|--------|--------|
| `latest-24h-min.json` | OpenClaw | 前端 |
| `latest-24h-all.json` | OpenClaw | 前端 |
| `source-status.json` | OpenClaw | 前端 |
| `curated/YYYY-MM-DD.json` | OpenClaw | 存档 |
| `archive.json` | OpenClaw | 去重 |

### 3.2 微信板块（Hermes）

| 文件 | 写入方 | 读取方 |
|------|--------|--------|
| `wechat-articles.json` | Hermes | 前端 |
| `wechat-manual.json` | Hermes | wechat-collector |

### 3.3 禁止行为

- ❌ OpenClaw 修改 `wechat-articles.json` 或 `wechat-manual.json`
- ❌ OpenClaw 修改 `wechat-collector-v2.py`
- ❌ Hermes 修改 `latest-24h-*.json` 或 `source-status.json`
- ❌ 微信文章混入 RSS 评分系统
- ❌ RSS 文章混入微信专区

---

## 四、提交规范

### OpenClaw 的提交格式

```
[rss] 更新 Google News 关键词
[rss] 调整噪声过滤规则
[curate] 调整精选阈值
[fix] 修复 RSS 采集 bug
[infra] 更新 workflow 配置
[data] 数据刷新 YYYY-MM-DDTHH:MM:SSZ
[docs] 更新雷达文档
```

### 禁止提交的内容

- ❌ 微信相关文章
- ❌ API keys / Tokens
- ❌ 本地测试文件（如 `test_regex.py`）
- ❌ 未清理的临时文件

---

## 五、冲突预防

### 5.1 文件冲突

**风险场景**：双方同时修改同一文件

**预防措施**：
- RSS 和微信使用不同文件，默认不冲突
- 修改 `assets/app.js` 或 `index.html` 前通知对方
- 重大变更前在 issue 或 PR 中讨论

### 5.2 数据冲突

**风险场景**：微信文章误入 RSS 评分

**预防措施**：
- `update_news.py` 只处理 RSS feeds
- 微信文章通过独立流程处理
- 前端分区展示，互不干扰

### 5.3 Workflow 冲突

**风险场景**：两次运行重叠导致推送冲突

**当前配置**：
```yaml
concurrency:
  group: update-ai-news-${{ github.ref }}
  cancel-in-progress: true
```

**改进建议**：
- 如果频繁冲突，改为 `cancel-in-progress: false`
- 增加运行间隔（如从 30 分钟改为 1 小时）

---

## 六、联合维护文件

以下文件需要双方协商修改：

| 文件 | 修改方 | 说明 |
|------|--------|------|
| `.github/workflows/update-news.yml` | 双方协商 | Workflow 配置影响整体流程 |
| `assets/app.js` | 双方协商 | 前端渲染逻辑 |
| `index.html` | 双方协商 | 页面结构 |
| `feeds/*.opml` | OpenClaw | RSS 信源配置 |

---

## 七、关键文件索引

### OpenClaw 专属

```
scripts/update_news.py               # RSS 采集
scripts/curated_collector.py         # 精选
scripts/ai_relevance.py              # 相关性评分
.github/workflows/update-news.yml    # Workflow
feeds/follow.example.opml            # 公开信源模板
data/latest-24h-min.json             # RSS 数据
data/latest-24h-all.json             # 全量数据
data/source-status.json              # 源状态
data/curated/YYYY-MM-DD.json         # 精选存档
```

### Hermes 专属

```
scripts/wechat-collector-v2.py       # 微信采集
data/wechat-articles.json            # 微信数据
data/wechat-manual.json              # 手动微信文章
```

### 共同维护

```
assets/app.js                        # 前端逻辑
index.html                           # 页面结构
docs/collaboration-guide.md          # 协作指南
docs/openclaw-collaboration-guide.md # 本文件
```

---

## 八、常见问题

### Q: OpenClaw 能修改微信相关代码吗？

A: 不建议。微信板块是 Hermes 的专属领域。如果有微信相关的 bug，应该报告给 Hermes 修复。

### Q: Hermes 能修改 RSS 相关代码吗？

A: 不建议。RSS 采集和评分是 OpenClaw 的专属领域。如果有 RSS 相关的 bug，应该报告给 OpenClaw 修复。

### Q: 为什么有三个微信采集器？

A: 历史遗留。`wechat-collector.py`（449行）、`wechat-collector-v2.py`（281行）、`wechat_collector.py`（173行）。推荐只保留 v2 版本。

### Q: 微信文章为什么不进入 RSS 评分？

A: 微信文章是独立板块，由 Hermes 手动添加，不经过 RSS 采集和评分流程。这样可以保持微信内容的独立性和可控性。

### Q: 如何检查数据管道是否正常？

A: 
1. 查看 GitHub Actions 运行日志
2. 检查 `data/latest-24h-min.json` 的 `generated_at`
3. 检查 `data/source-status.json` 的 feeds 状态
4. 访问网站确认数据展示

---

## 九、快速参考

### OpenClaw 常用命令

```bash
# 运行 RSS 采集
python scripts/update_news.py --output-dir data

# 运行精选
python scripts/curated_collector.py --data-path data/latest-24h-min.json

# 检查源状态
cat data/source-status.json | jq '.summary'

# 验证 JSON 结构
python -c "import json; d=json.load(open('data/latest-24h-min.json')); print(d.keys())"

# 查看最近提交
git log --oneline -5
```

### 联系方式

- **OpenClaw**: 通过 GitHub Issues 沟通
- **Hermes**: Jack（Hermes Agent）

---

*本文档已合并到 `docs/radar-collaboration-guide.md`，请以该文件为准。本文件保留作为历史参考。*

*本文档由 OpenClaw 创建，供所有维护者参考。如有更新请通知双方。*
