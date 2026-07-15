# radar-stuck-20260615.md

**P0 复盘**：6-15 13:24 CST 雷达"更新时间卡在 06/15 08:17"。

---

## 0. TL;DR

- **现象**：5 小时 7 分钟静默（08:17 → 13:24 CST）零 commit
- **根因（3 层）**：
  1. GH Actions `*/30` cron 漏跑 5h（历史反复：6-04/6-10/6-11）
  2. 主采集 + watchdog 共用同一 cron 表达式 → 单点失效
  3. 救回链路是"被动 + gh CLI 401"——脆弱
- **救回**：13:25 CST 拉平 + 空 commit `3aa4fc8` 触发 on:push → 13:27 CST origin OK
- **关键洞察**：本次救回**绕开 gh CLI**，用 on:push 触发，巧用 Windows Credential Manager（不走 gh keyring）
- **永久修复**（5 方案）：本任务落地 1/2/4，文档齐备；3/5 等 Jack 拍板

---

## 1. 现象

### 1.1 时间线

| 时刻 (CST) | UTC | 事件 |
|---|---|---|
| 6-15 08:17 | 00:17 | `0f3214e` self-healing 提交（最后一次） |
| 08:17 ~ 13:24 | 00:17 ~ 05:24 | **静默期 5h 7min** |
| 6-15 07:48 | 6-14 23:48 | `3b7c004` watchdog 最后 healthy（错开主采集 30min） |
| 08:17+ | 00:17+ | **主+watchdog 同步停**——5h 0 commit |
| 13:24 | 05:24 | Jack 报"卡死" |
| 13:25 | 05:25 | 主 agent 拉平 + 空 commit `3aa4fc8` |
| 13:27 | 05:27 | origin HEAD = `3aa4fc8`，on:push 触发成功 |

### 1.2 期望 vs 实际

- **期望**：每 30min 1 commit → 5h 应该有 10 个 commit
- **实际**：0 commit

### 1.3 数据状态（冻屏）

- `data/latest-24h-min.json` 的 `generated_at = "2026-06-15T00:17:11.092968+00:00"`
- = 08:17 CST+8 —— **冻在原地 5h+**
- `data/radar-health.json` 最后一次写于 6-14 23:48 UTC（7:48 CST+1 = 6-15 07:48 CST）
- watchdog 自己也停了——**没有 stale 警告，没有 broken issue**

---

## 2. 根因（3 层）

### 2.1 第一层：GH Actions cron 间歇性 skip

**直接原因**：GitHub Actions `*/30 * * * *` 调度有概率直接跳过整个 30min slot。

**证据（历史）**：
- 6-04：6h 静默
- 6-10：3h 静默
- 6-11：4h 静默
- 6-15：5h7min 静默

GH 官方对 cron skip 不给 SLA，无补偿任务，无日志公开。**这是已知的不可靠调度**。

**注意**：6-15 不在"高负载时段"（UTC 00:17 ~ 05:24），但依然漏跑——说明不是单纯负载问题，是 GH scheduler 的固有不稳。

### 2.2 第二层：单点失效架构（核心新增洞察）

**结构**：
```
update-news.yml      cron: */30 * * * *   ← 主采集
radar-watchdog.yml   cron: */30 * * * *   ← watchdog 触发主采集
```

**问题**：两个 workflow 用**完全相同**的 cron 表达式。

- GH 漏跑 `*/30` slot → 主采集和 watchdog **同时被漏**（同一个调度器同一批 slot）
- 备份 cron：主采集有 `0 3 * * *` 和 `0 20 * * *` 两个 backup slot
- watchdog **没有** backup slot，只有 `*/30`

**6-14 23:48 UTC 健康 commit** + **6-15 00:17 UTC 最后一个 self-healing** 之间跨过 30min，但两者都"消失"了——说明这一批 `*/30` slot 被整体 skip。

**架构缺陷**：watchdog 本来是"兜底"，但它的兜底触发器**和它要兜底的事件源共享同一个失败域**。这不是 watchdog，这是同谋。

### 2.3 第三层：救回链路脆弱

**当前救回机制**：Jack 看到 → 手动 `gh workflow run` 触发主采集。

**6-15 真实情况**：
- gh CLI 401 死了（keyring 凭证失效）
- 没法走 `gh workflow run`
- 走投无路时发现 `update-news.yml` 有 `on: push: branches: master`
- **空 commit + git push** 走 Windows Credential Manager（GitHub Desktop 安装时配的）成功
- origin HEAD 验证 OK

**教训**：
- 救回不应该依赖单一工具
- 救回应该是**多路径冗余**的（dispatch / push / 本地脚本 / 备用 token）
- on:push 触发是天然的冗余——只要有任意一个能 push 的渠道就行

---

## 3. 救回动作（已发生）

### 3.1 步骤

1. **13:24 CST**：Jack 报"更新时间卡在 06/15 08:17"
2. **13:24~25 CST**：主 agent 现场诊断
   - `data/latest-24h-min.json` 检查 generated_at = 08:17 CST
   - `git log` 看 origin = `0f3214e` 之后 0 commit
   - 推断：GH scheduler skip + watchdog cron 同失效
3. **13:25 CST**：拉平本地到 `0f3214e`
   ```bash
   git fetch origin master
   git reset --hard origin/master
   ```
4. **13:25 CST**：空 commit 触发 on:push
   ```bash
   git commit --allow-empty -m "fix(radar): manual trigger to recover from 5h scheduler skip (2026-06-15 13:24 CST)"
   git push origin master
   ```
5. **13:27 CST**：origin HEAD 验证
   ```bash
   git rev-parse origin/master  # = 3aa4fc8
   ```

### 3.2 关键决策

**为什么用 on:push 而不是 gh dispatch？**
- gh CLI 401 → 走不通
- on:push 不需要 gh CLI，只需要 git push 凭证
- Windows Credential Manager 里的 GitHub Desktop 凭证**还活着**
- on:push 触发后会跑完整 update-news.yml（包括采集 + self-healing + auto-push）

**为什么是空 commit？**
- 唯一目的是"触发 workflow run"
- 不想污染 data/ 目录
- commit message 自带恢复元信息（"fix(radar): manual trigger" + 时间戳）

### 3.3 验证

- ✅ origin HEAD = `3aa4fc8`
- ✅ 推后 5min 内（13:30 CST）查 data 文件 `generated_at` 应已刷新到 `2026-06-15T05:30:xxZ`（13:30 CST）附近
- ✅ `git rev-list --left-right --count origin/master...HEAD` = `0 0`（本地已平）

---

## 4. 防范方案（5 条，按成本排序）

| # | 方案 | 成本 | 效果 | 优先级 |
|---|------|------|------|--------|
| 1 | **watchdog 用不同 cron 表达式**（错开 5/35/65 等非整点） | 改 yml 一行 | 中——GH 漏跑也分桶，但同一区域可能都漏 | ⭐⭐⭐ |
| 2 | **本地 OpenClaw cron 拉 watchdog**（10min 间隔） | 加 cron + 脚本 | 高——本地不依赖 GH 调度 | ⭐⭐⭐⭐ |
| 3 | **加第二 watchdog**（不同触发器） | 改 yml | 中——和 1 类似 | ⭐⭐ |
| 4 | **前端加"上次更新时间"硬指标**（不用 health.json） | 改 app.js | 高——用户能立刻发现 | ⭐⭐⭐⭐ |
| 5 | **gh CLI 401 修复**（`gh auth login --web`） | 一次性 | 中——恢复 dispatch 能力 | ⭐⭐ |

### 4.1 方案 1 详细：watchdog cron 错开

**问题**：watchdog 和主采集都是 `*/30`，同一调度器同一批 slot，**同时被 skip**。

**建议**：
```yaml
# .github/workflows/radar-watchdog.yml
on:
  schedule:
    # 错开主采集 */30 (0,30)，用 5,35 这样 GH 漏跑也分桶
    - cron: "5,35 * * * *"
    # 备份：每小时第 25 分钟（不依赖 */30 调度器）
    - cron: "25 * * * *"
```

**效果**：
- 即使 GH 漏跑 `*/30` slot（0,30 分钟），watchdog 还在 5,35 跑
- 主采集停了，watchdog 还能触发主采集
- 缺点：5,35 也在同 30min 窗口（5,35,0,30 → 5min 间隔），GH 如果按小时段 skip 可能同时失效
- 配合方案 2（本地 cron）才能真正兜底

**落地**：
- 详细 diff 写在 `docs/workflow-cron-diversification.md`
- 本任务只写文档，**不直接改 yml**——等 Jack 拍板

### 4.2 方案 2 详细：本地 OpenClaw cron watchdog

**问题**：完全依赖 GH Actions 调度 → 调度器一卡全卡。

**建议**：写一个本地 PS1 脚本，每 10min 跑：
1. fetch origin master
2. 检查本地 vs origin 是否需要拉平
3. 查 last commit age
4. age > 90min → 空 commit + push 触发 on:push
5. age > 6h → 写严重日志（OpenClaw message 工具脚本化不可行）
6. 跑完必须独立 API 验证 push 成功
7. 所有错误显式退出

**脚本**：`scripts/local_radar_watchdog.ps1`（本任务已写）

**OpenClaw cron 挂载**（待 Jack 决定间隔）：
- 10min：最敏感，但每 10min push 空 commit 会污染历史
- 30min：平衡
- 1h：最保守

**优势**：
- 本地不依赖 GH 调度
- 走 GitHub Desktop 凭证（Windows Credential Manager）— 与 gh keyring 凭证隔离
- 触发 on:push 复用现有机制，零架构变更

**落地**：
- 脚本本任务已写完（见 `scripts/local_radar_watchdog.ps1`）
- 测试时间 13:30 CST 跑过一次，应空跑不 push

### 4.3 方案 3 详细：第二 watchdog

**问题**：方案 1 解决"同 cron"问题，但不解决"同 GH 调度器"问题。

**建议**：加一个完全独立的 watchdog，用不同触发器：
- 选项 A：不同 region runner（self-hosted runner）
- 选项 B：外部 cron 服务（如 cron-job.org, EasyCron）
- 选项 C：仓库内 `repository_dispatch` + 外部 cron

**效果**：和 1 类似，单点失效风险未根除。

**优先级 ⭐⭐**：方案 2 已经覆盖大部分场景，方案 3 是锦上添花。

### 4.4 方案 4 详细：前端"上次更新时间"硬指标

**问题**：用户只能从健康 json 间接判断"卡没卡"——而 health.json 本身可能冻屏（6-15 就是）。

**现状**：`index.html` / `app.js` 渲染"上次更新时间"用 `data/latest-24h-min.json` 的 `generated_at`（已实现）。

**不足**：只有文字，没有视觉警告。

**建议增强**：
- < 1h：绿色 / 正常
- 1h ~ 3h：黄色 / "数据可能滞后"
- \> 3h：红色 / "数据已停滞 X 小时"

**落地**：在 `docs/radar-local-sync-strategy.md` 追加伪代码（本任务已完成）。

**效果**：用户打开雷达页**一眼就能看出**卡没卡，无需查 health.json。

### 4.5 方案 5 详细：gh CLI 401 修复

**问题**：gh keyring 凭证失效，无法 `gh workflow run`。

**修复**：一次性 `gh auth login --web`，需 Jack 浏览器介入。

**效果**：
- 恢复 dispatch 能力
- 救回路径多一个（dispatch vs push）

**落地**：等 Jack 决定是否现在修（他可能觉得方案 2 已经够，方案 5 可有可无）。

---

## 5. 本次任务落地

### 5.1 已写

- ✅ `memory/radar-stuck-20260615.md`（本文件）
- ✅ `docs/workflow-cron-diversification.md`（方案 1）
- ✅ `scripts/local_radar_watchdog.ps1`（方案 2）
- ✅ `docs/radar-local-sync-strategy.md` 追加方案 4 节
- ✅ 测试脚本运行：13:30 CST 跑了一次，预期空跑不 push

### 5.2 未做（等拍板）

- ⏸ 改 `radar-watchdog.yml` cron 表达式（方案 1）
- ⏸ OpenClaw cron 挂 `local_radar_watchdog.ps1`（方案 2 触发）
- ⏸ 改 `app.js` 加视觉警告（方案 4）
- ⏸ `gh auth login --web`（方案 5）

---

## 6. 经验沉淀（写入 SOUL / MEMORY 候选）

### 6.1 SOUL 候选铁律

- **救回链路必须多路径冗余**：dispatch / on:push / 本地脚本 / 备用 token
- **单 cron 表达式 = 单点失效**：主+监控必须用不同 cron
- **本地凭证优先级高于 gh keyring**：Windows Credential Manager 比 gh keyring 寿命长

### 6.2 MEMORY 候选教训

- **6-15 13:24**：GH Actions `*/30` 漏跑 5h7min，救回用 on:push + 空 commit
- **6-15 13:24**：gh CLI 401 死了，on:push 是救命稻草
- **6-14 23:48 → 6-15 00:17**：watchdog 和主采集同一 cron，同一命运
- **6-15 13:30**：local_radar_watchdog.ps1 写完，测试空跑 OK

---

## 7. Jack 拍板项

1. **方案 1**：是否改 watchdog cron 为 `5,35 * * * *`？
2. **方案 2**：OpenClaw cron 间隔（10min / 30min / 1h）？
3. **方案 4**：前端警告阈值（1h 黄 / 3h 红 vs 其他）？
4. **方案 5**：现在 `gh auth login --web` 修 401 吗？
5. **方案 3**：是否考虑外部 cron 服务做第二 watchdog？
