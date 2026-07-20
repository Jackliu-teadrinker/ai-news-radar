# AI News Radar 工作流文档

> 本文档记录雷达从数据采集到网站发布的完整流程，包括架构设计、各环节逻辑、数据格式和复用指南。
> 最后更新：2026-07-20

---

## 一、系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Actions (云端自动运行)                   │
│                                                                      │
│   Cron 触发 (每30min + 03:00 + 20:00 CST)                           │
│         │                                                           │
│         ▼                                                           │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  Step 1: update_news.py                                    │    │
│   │   - 解析 feeds/follow.example.opml (10条 RSS)               │    │
│   │   - 并发抓取所有 feed (max_workers=8, timeout=20s)           │    │
│   │   - feedparser 解析 entry                                   │    │
│   │   - 标题/URL 归一化 → SHA1 去重                             │    │
│   │   - 五维评分 relevance×100+authority+depth+writing+timeliness │
│   │   - 英文标题 Google Translate 翻译                           │    │
│   │   - 噪声过滤: ETF/股票/扫地机器人/概念股/研报                  │    │
│   │   - 跨 feed 去重 (同标题不同来源)                            │    │
│   │   - 时间窗口: 前一天 19:00 CST → 当前                       │    │
│   │   - 归档 dedup (archive.json 21天窗口)                      │    │
│   │   - 输出: latest-24h-min.json (≤500条)                      │    │
│   │          latest-24h-all.json (全量)                         │    │
│   │          source-status.json (采集状态)                       │    │
│   │          archive.json (增量追加)                             │    │
│   └──────────────────────────────────────────────────────────┘    │
│         │                                                           │
│         ▼                                                           │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  Step 2: curated_collector.py                              │    │
│   │   - 读取 latest-24h-min.json                               │    │
│   │   - score ≥ 80 过滤 → top 高质量文章                        │    │
│   │   - URL SHA1 去重 (跨天 dedup)                             │    │
│   │   - 每天最多 50 条                                         │    │
│   │   - 输出: data/curated/YYYY-MM-DD.json                     │    │
│   └──────────────────────────────────────────────────────────┘    │
│         │                                                           │
│         ▼                                                           │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  Step 3: git auto-commit + GitHub Pages 部署               │    │
│   │   - 检测 data/ scripts/ index.html 变更                   │    │
│   │   - radar-bot 用户自动 commit + push                       │    │
│   │   - GitHub Pages 读取 data/*.json 静态托管                  │    │
│   └──────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        前端网站 (GitHub Pages)                        │
│                                                                      │
│   index.html + assets/app.js                                          │
│   - 读取 latest-24h-min.json (AI精选模式, ≤500条)                    │
│   - 读取 latest-24h-all.json (全量模式)                              │
│   - 前端筛选/排序/搜索/站点过滤                                      │
│   - 实时显示更新时间、站点统计                                        │
│   - 微信公众号专区 (wechat-articles.json)                            │
│                                                                      │
│   站点地址: https://jackliu-teadrinker.github.io/ai-news-radar/      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、RSS 信源配置

### 2.1 信源文件

**位置**: `feeds/follow.example.opml`

文件格式 OPML，每条 `<outline>` 对应一个 RSS feed：

```xml
<outline text="信源名称" xmlUrl="https://news.google.com/rss/search?q=..." />
```

**当前配置 (10条)**:

| 标签 | 查询关键词 | 语言 |
|------|-----------|------|
| 国外人形机器人资讯 | humanoid robot | EN |
| 国外具身智能资讯 | embodied intelligence OR embodied AI | EN |
| GN: BCI | brain computer interface OR BCI OR neural interface | EN |
| 国外机器人资讯 | robot | EN |
| 国外物理AI资讯 | physical AI | EN |
| GN: 人形机器人 | 人形机器人 | CN |
| GN: 具身智能 | 具身智能 | CN |
| GN: 脑机接口 | 脑机接口 OR 神经接口 OR 脑电接口 | CN |
| GN: 机器人 | 机器人 | CN |
| GN: 物理AI | 物理AI | CN |

### 2.2 添加新信源

在 `feeds/follow.example.opml` 中添加新的 `<outline>` 节点，提交后 GitHub Actions 自动部署。

> 注意: 不提交私有 OPML 文件，始终修改 `follow.example.opml` 作为公开模板。

---

## 三、采集脚本详解

### 3.1 update_news.py（核心采集）

**入口命令**:
```bash
python scripts/update_news.py \
  --output-dir data \
  --window-hours 24 \
  --rss-opml feeds/follow.example.opml \
  --archive-days 21
```

**处理流程**:

```
OPML 解析
    │
    ▼
并发抓取 (ThreadPoolExecutor, max_workers=8)
    │ 每个 feed: requests.get → feedparser.parse
    ▼
标题/URL 归一化 → SHA1(title+url) 单次去重
    │
    ├── WeChat 文章注入 (wechat_collector.py)
    │   - wechat-manual.json (手动添加)
    │   - wechat-articles.json (旧数据兼容)
    │   - URL dedup against RSS items
    │
    ▼
跨 feed 去重 (BUG#1修复)
    │ 同标题但不同 URL 的文章，保留 score 最高
    ▼
归档去重 (archive.json, 21天窗口)
    │ 已在 archive 中的 article id 不重复入
    ▼
噪声过滤
    - ETF / 股票 / 股价 / 涨跌 / 上市 / IPO
    - 扫地机器人 (追觅/科沃斯/云鲸/石头/roomba/robovac...)
    - 概念股 / 评级 / 买入 / 卖出 / 目标价
    - 财报 / 营收 / 利润 / 亏损
    - 回购 / 分红 / 配股
    ▼
时间窗口过滤
    - 窗口: 前一天 19:00 CST → 当前时间
    - 无 published_at 的文章默认通过（有日志警告）
    ▼
中文翻译 (英文标题)
    - Google Translate free API (client=gtx)
    - 429 时指数退避重试 (最多3次)
    - max_workers=2 防止触发限速
    ▼
五维评分
    │ score = relevance×100 + authority + depth + writing_value + timeliness
    ▼
排序输出
    - latest-24h-min.json (top 500, AI精选模式用)
    - latest-24h-all.json (全量)
    - source-status.json (各feed采集状态)
    - archive.json (增量追加)
```

**五维评分体系**:

| 维度 | 说明 | 分值范围 |
|------|------|---------|
| relevance | 行业相关性 (TIER1/2/3 关键词匹配) | 0.35~0.80 |
| authority | 来源权威性 (Google News: 15, 其他: 10) | 10~15 |
| depth | 内容深度 (description ≥ 100字: +5) | 0~5 |
| writing_value | 写作价值 (description ≥ 100字: +5) | 0~5 |
| timeliness | 时效性 (越新分越高, 30-age_hours) | 0~30 |

**Relevance TIER**:

| TIER | 关键词 | 分值 |
|------|--------|------|
| TIER1 | humanoid robot, 人形机器人, 具身智能, 脑机接口... | 0.80 |
| TIER2 | robot, robotics, Unitree, 宇树, 智元, 灵巧手... | 0.65 |
| TIER3 | physical AI, dexterous manipulation, robot learning | 0.50 |
| 无匹配 | 其他 | 0.35 |

**标签分类逻辑 (GN_LABEL_MAP)**:
- `humanoid`: 人形机器人相关
- `embodied_ai`: 具身智能相关
- `brain_computer`: 脑机接口相关
- `physical_ai`: 物理AI相关
- `robotics`: 通用机器人
- BUG修复: 标题含"机器人/人形/具身"时，强制将 `physical_ai` 降级为 `robotics`

### 3.2 curated_collector.py（每日精选）

**入口命令**:
```bash
python scripts/curated_collector.py \
  --data-path data/latest-24h-min.json \
  --curated-dir data/curated
```

**处理逻辑**:
```
读取 latest-24h-min.json
    │
    ▼
score ≥ 80 过滤 (可调整阈值)
    │
    ▼
URL SHA1 去重 (跨天, 持久化 dedup)
    │
    ▼
每天最多 50 条 (超出按 score 截断)
    │
    ▼
输出: data/curated/YYYY-MM-DD.json
      字段精简: id/title/title_zh/url/published_at/source/
                site_name/description/total_score/relevance/
                authority/depth/timeliness/writing_value/ai_label
```

### 3.3 wechat_collector.py（微信公众号采集）

**数据来源（优先级从高到低）**:
1. `data/wechat-manual.json` — 用户手动添加的文章
2. `data/wechat-articles.json` — 雷达历史数据中的微信文章

**逻辑**:
- 加载后按 URL 去重
- 尝试抓取文章真实发布时间（HTML 中解析 `YYYY-MM-DD HH:MM`）
- 标准化字段格式，与 RSS 文章格式对齐
- 结果传入 `update_news.py` 合并

---

## 四、数据文件说明

| 文件 | 用途 | 生成方式 |
|------|------|---------|
| `latest-24h-min.json` | 前端AI精选模式数据（≤500条） | update_news.py |
| `latest-24h-all.json` | 前端全量模式数据 | update_news.py |
| `source-status.json` | 各RSS feed采集状态（成功/失败/条数） | update_news.py |
| `archive.json` | 21天全局去重池 | update_news.py 增量追加 |
| `data/curated/YYYY-MM-DD.json` | 当日策展精选（每天≤50条） | curated_collector.py |
| `wechat-articles.json` | 微信公众号文章缓存 | 外部注入 |

---

## 五、GitHub Actions 工作流

**文件位置**: `.github/workflows/update-news.yml`

### 5.1 触发条件

| 触发方式 | 说明 |
|---------|------|
| `push` (任何分支) | 代码变更自动触发 |
| `schedule: */30 * * * *` | 每30分钟定时 |
| `schedule: 0 3 * * *` | 每天 03:00 UTC (11:00 CST) |
| `schedule: 0 20 * * *` | 每天 20:00 UTC (04:00 CST) |
| `workflow_dispatch` | 手动触发（GitHub UI 或 `gh` CLI） |

### 5.2 执行步骤

```yaml
1. Checkout (fetch-depth: 0)
2. Python 3.11 + pip cache
3. pip install -r requirements.txt
4. python -m py_compile (语法校验)
5. python scripts/update_news.py          # 核心采集
6. python scripts/curated_collector.py   # 策展精选
7. 更新 index.html version hash (缓存穿透)
8. git auto-push (radar-bot, 仅变更时提交)
9. GitHub Pages 部署 (actions/deploy-pages)
```

### 5.3 并发控制

```yaml
concurrency:
  group: update-ai-news-${{ github.ref }}
  cancel-in-progress: true
```
同一分支并行运行的新 workflow 会被自动取消，避免资源浪费。

### 5.4 手动触发命令

```bash
# 通过 gh CLI
gh workflow run update-news.yml --repo Jackliu-teadrinker/ai-news-radar

# 或通过 GitHub API
curl -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/Jackliu-teadrinker/ai-news-radar/actions/workflows/update-news.yml/dispatches \
  -d '{"ref":"master"}'
```

---

## 六、本地运行指南

### 6.1 环境准备

```bash
git clone https://github.com/Jackliu-teadrinker/ai-news-radar.git
cd ai-news-radar
pip install -r requirements.txt
```

### 6.2 完整本地运行

```bash
# 1. 采集 + 策展
python scripts/update_news.py \
  --output-dir data \
  --window-hours 24 \
  --rss-opml feeds/follow.example.opml \
  --archive-days 21

python scripts/curated_collector.py \
  --data-path data/latest-24h-min.json \
  --curated-dir data/curated

# 2. 启动本地预览
python -m http.server 8080
# 打开 http://localhost:8080
```

### 6.3 环境变量（可选）

| 变量 | 默认值 | 说明 |
|------|-------|------|
| `WECHAT_COLLECTOR_ENABLED` | `1` | 是否启用微信采集 |
| `WECHAT_KEYWORDS` | (空) | 微信搜索关键词（逗号分隔，暂未启用） |
| `WECHAT_HOURS` | `24` | 微信文章时间范围（小时） |
| `WECHAT_MAX_PER_KW` | `10` | 每关键词最大结果数（暂未启用） |

---

## 七、已知问题与修复记录

| BUG | 描述 | 修复方案 | 日期 |
|-----|------|---------|------|
| BUG#1 | 跨 feed 去重失败：同文章不同 URL 被重复收录 | 引入 `normalize_title_for_dedup()` 归一化标题去重 | 2026-07-13 |
| BUG#2 | `physical_ai` 标签误覆盖人形机器人文章 | 标题含"机器人/人形/具身"时强制降级为 `robotics` | 2026-07-13 |
| 翻译限速 | Google Translate 429 导致批量翻译静默失败 | 指数退避重试 + max_workers=2 | 2026-07-13 |
| 标题源缀 | GN 在标题末尾加 ` - Source Name`，导致误去重 | 正则剥离末尾 ` - Source` 后缀 | 2026-07-13 |
| 时间窗口 | 滑动24h窗口在早晨运行时漏掉夜间内容 | 恢复 CST 19:00 锚点，固定窗口起止 | 2026-07-14 |
| 空时间戳 | 无 published_at 的文章被硬性过滤 | 改为默认通过 + 日志警告 | 2026-07-13 |

---

## 八、扩展与复用

### 8.1 接入新 RSS 源

1. 确认 RSS/Atom feed URL 可访问
2. 编辑 `feeds/follow.example.opml`，添加 `<outline>` 节点
3. 确定分类标签（在 `GN_LABEL_MAP` 中添加映射）
4. 提交 PR / commit，Actions 自动部署

### 8.2 修改评分阈值

```python
# scripts/update_news.py
TIER1 = ['humanoid robot', ...]  # 调整关键词影响 relevance
SCORE_THRESHOLD = 80              # curated_collector.py 精选阈值
```

### 8.3 调整时间窗口

```bash
# 默认: 前一天 19:00 CST → 当前
# 可通过 --window-from 指定起始日期
python scripts/update_news.py --window-from 2026-07-01
```

### 8.4 接入新数据采集源

在 `update_news.py` 的 `run()` 函数中，采集后、评分前，注入新的数据源：

```python
# 示例: 注入新数据源
custom_items = your_custom_collector()
all_items.extend(custom_items)
```

---

## 九、快速参考

```bash
# 克隆
git clone https://github.com/Jackliu-teadrinker/ai-news-radar.git

# 安装依赖
pip install feedparser requests

# 本地运行
python scripts/update_news.py --output-dir data --window-hours 24

# 策展精选
python scripts/curated_collector.py --data-path data/latest-24h-min.json

# 手动触发 Actions
gh workflow run update-news.yml --repo Jackliu-teadrinker/ai-news-radar

# 查看 Actions 状态
gh run list --workflow=update-news.yml --repo Jackliu-teadrinker/ai-news-radar

# 本地预览
python -m http.server 8080
```
