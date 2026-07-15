# workflow-cron-diversification.md

**问题**：watchdog 和主采集共用 cron 表达式 `*/30 * * * *` → 同一调度器同一批 slot 漏跑时**双双失效**（6-15 5h7min 静默根因之一）。

**性质**：架构性单点失效。不是"watchdog 没工作"，是"watchdog 失效域和它要兜底的事件源重叠"。

---

## 1. 现状

### 1.1 主采集 `.github/workflows/update-news.yml`

```yaml
on:
  push:
    branches:
      - master
  schedule:
    # Primary: every 30 min
    - cron: "*/30 * * * *"
    # Backup: 3 AM UTC = 11 AM Beijing
    - cron: "0 3 * * *"
    # Backup: 8 PM UTC = 4 AM Beijing (off-peak recovery)
    - cron: "0 20 * * *"
  workflow_dispatch:
```

**主采集有 3 个 cron 入口**：primary + 2 个 backup。

### 1.2 watchdog `.github/workflows/radar-watchdog.yml`

```yaml
on:
  schedule:
    # every 30 minutes, offset 5 min from main collection (*/30 -> */30)
    - cron: "*/30 * * * *"
  workflow_dispatch:
```

**watchdog 只有 1 个 cron 入口**：和主采集 primary **完全相同**。

注释说 "offset 5 min"，**但实际 cron 表达式一样**——这是历史注释错误 / 已废弃的偏移计划。

---

## 2. 问题分析

### 2.1 GH Actions cron 漏跑模式

GitHub Actions 文档对 cron 调度有"best effort"声明：
- 不保证精确时间
- 长时间运行的仓库会出现 skip
- 跳过时不公开原因
- **没有补偿机制**

6-15 实证（最近 30 天）：
- 6-04：6h 静默
- 6-10：3h 静默
- 6-11：4h 静默
- 6-15：5h7min 静默

**已知不可靠**。问题不是"会不会漏"，是"漏了怎么办"。

### 2.2 6-15 单点失效路径

```
00:17 UTC  → 0f3214e self-healing（最后一个）
00:30 UTC  → 期望主采集（*/30 slot）→ SKIP
00:30 UTC  → 期望 watchdog（*/30 slot）→ SKIP
01:00 UTC  → 期望主采集 → SKIP
01:00 UTC  → 期望 watchdog → SKIP
...
05:00 UTC  → 期望主采集 → SKIP
05:00 UTC  → 期望 watchdog → SKIP
05:17 UTC  → 期望 backup "0 3 * * *" = 03:00 UTC
              03:00 UTC 之前就漏了，所以这个 backup 也没救
              实际 03:00 UTC 也没跑（验证方法：查那个时间段的 actions log）
05:24 UTC  → Jack 报卡死
```

**关键**：03:00 UTC 的 backup cron 也漏了——说明不是"特定 slot"漏，是**整个时间段 GH 调度器不稳**。

### 2.3 期望：分桶失效

如果 watchdog cron 错开主采集（如 `5,35`），理论失败域如下：
- 主采集 `0,30` slot 漏 → watchdog `5,35` 还能跑
- watchdog `5,35` 也漏 → 看主采集 backup `0 3, 0 20` 还在不在
- 至少 3 个独立 cron 入口，**同时全部漏的概率 << 单 cron 漏的概率**

---

## 3. 建议：watchdog cron 错开 + 加 backup

### 3.1 建议改法

```yaml
# .github/workflows/radar-watchdog.yml
on:
  schedule:
    # 错开主采集 */30,用 5,35(每 30min 跑一次,但 offset 5min)
    - cron: "5,35 * * * *"
    # Backup 1: 每小时第 25 分钟(独立小时分桶)
    - cron: "25 * * * *"
    # Backup 2: 每天 6 AM UTC + 6 PM UTC(独立时段)
    - cron: "0 6,18 * * *"
  workflow_dispatch:
```

### 3.2 Diff 片段

```diff
 on:
   schedule:
-    # every 30 minutes, offset 5 min from main collection (*/30 -> */30)
-    - cron: "*/30 * * * *"
+    # Offset 5 min from main collection to avoid same-slot skip
+    - cron: "5,35 * * * *"
+    # Backup: independent hourly bucket (every hour at :25)
+    - cron: "25 * * * *"
+    # Backup: independent time-of-day slots
+    - cron: "0 6,18 * * *"
   workflow_dispatch:
```

### 3.3 为什么这么选

| cron | 含义 | 失败域 |
|---|---|---|
| `5,35 * * * *` | 每小时 5/35 分跑 | 错开主采集的 0/30 |
| `25 * * * *` | 每小时 25 分 | 完全独立分桶,即使 5/35 漏了还有 25 兜底 |
| `0 6,18 * * *` | 每天 UTC 6:00 / 18:00 | 独立时段,每天 2 次兜底 |

3 个 cron 入口 = 3 个独立失败桶，全部同时漏的概率极低。

### 3.4 副作用 / 注意

- **不**修改主采集的 cron（主采集 3 个 backup 已够，且有 on:push 兜底）
- **不**取消 concurrency 控制（避免堆积）
- **不**改 watchdog 的"trigger main collection"逻辑——只是在 schedule 上错开
- 每次 watchdog 跑会写 `data/radar-health.json` commit——3 个 cron = 每天约 48 + 24 + 2 = 74 commit（比现在 48 多 26）
- 接受这个 commit 频率：health.json 本来就是高频信号

### 3.5 配合方案 2 才是真兜底

**重要**：cron 错开只是减少失败概率，**不根除**。GH Actions 调度器固有不稳（已知事实），想 100% 可靠必须本地兜底。

配合 `scripts/local_radar_watchdog.ps1`（方案 2）：
- 本地 cron 每 30min 跑
- age > 90min 自动空 commit + push → 触发 on:push
- 与 GH Actions 完全独立的失败域

**两条腿走路**：
- GH Actions cron 错开（方案 1）：减小漏跑概率
- 本地 cron 兜底（方案 2）：漏跑也不怕

---

## 4. 验证 / 监控

### 4.1 短期（落地后 1 周）

观察以下指标：
- `data/radar-health.json` 的 `checked_at` 字段密度（每 30min 应有 1 个）
- actions 页面 watchdog workflow 的 run 频率
- 主采集 self-healing commit 间隔

### 4.2 长期（落地后 1 月）

- 静默期平均长度
- 静默期最长长度
- "Jack 报卡"频率（应趋近 0）

### 4.3 异常报警

如果 `data/radar-health.json` 的 `commit_age_minutes` 持续 > 90：
- 说明方案 1 + 方案 2 都失效
- 进入方案 3 评估（外部 cron 服务）

---

## 5. 落地状态（本轮）

- ✅ 写本文档
- ⏸ 修改 `radar-watchdog.yml`——**等 Jack 拍板**

---

## 6. Jack 拍板项

1. **是否接受 3 个 cron 入口？**（每天 74 commit 频率）
2. **是否同时加 backup `0 6,18 * * *`？**（更激进 vs 更保守）
3. **是否同时启动方案 2？**（本地 cron 兜底，本任务已写完脚本）
4. **是否需要回滚机制？**（如 watchdog 误判重复触发，添加 cooldown 字段）
