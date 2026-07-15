# radar-local-sync-strategy.md

**问题**：本地工作树长期落后 origin/master 50 commit，导致 Jack 无法 debug / 改代码 / 本地验证。
**现象**：6-15 13:13 CST 本地 HEAD = 03ef804，origin HEAD = 0f3214e，落后 50 commit。
**性质**：运维盲区（不是雷达本身卡了，是 Jack 的视野滞后）。

---

## 1. 根因分析

### 1.1 物理结构
- **origin/master**：托管在 GitHub。`radar-watchdog.yml` 每 30 分钟自动跑一次，发现异常就触发 self-healing commit。每小时大约 2~4 个 commit。
- **本地工作树** `C:\Users\86571\ai-news-radar-gh`：**只在 Jack 主动操作时才更新**。没有 cron，没有 hook，没有任何被动同步机制。

### 1.2 数字层面的暴露
- watchdog 周期：30 min
- 本地最坏滞后：取决于 Jack 上次操作时间
- 6-15 真实值：~4 小时 + 50 commit
- 这意味着 Jack 看到的代码视图是 4h+ 前的 reality。如果 watchdog 在这 4h 内修了某个 bug，Jack 本地无法感知。

### 1.3 为什么 6-11 P0 修复至今没爆？
- watchdog + self-healing 是**全自动**闭环：检测 → 修 → commit → push，不需要本地介入。
- 所以即使本地 50 commit 落后，**雷达本身确实没卡**（health.json 报 healthy age=39min）。
- 但这只是"系统自愈力强"，**不等于本地没问题**。

### 1.4 真正的风险
如果未来某次 P0/P1 修复需要本地 debug：
1. Jack 在 03ef804 上手改
2. 改完 push → 必然被 non-fast-forward reject（50 commit 在前面）
3. 心态炸（"又卡了"）
4. 浪费时间在冲突解决上，而不是真 bug 上

这才是"卡死"的真相。**不是系统卡，是 Jack 的工作流卡。**

---

## 2. 三层方案

| 方案 | 实施成本 | 推荐度 | 触发时机 |
|---|---|---|---|
| **A. 本地 cron 拉取**（主推） | 中（写脚本 + 配 cron） | ⭐⭐⭐ | 被动，每 N 小时 |
| B. watchdog 增强：health.json 加 `local_drift` 字段 | 低（改 workflow） | ⭐⭐ | 被动，但 Jack 必须主动 fetch 才看得到 |
| C. 接受现状，靠 git fetch 一次性同步 | 0 | ⭐ | 主动，仅 Jack 手敲 |

**推荐 A**：彻底闭环。Jack 醒来打开就是最新代码。

---

## 3. 方案 A 详细规格

### 3.1 脚本：`scripts/local_sync.ps1`

**职责**：本地 git fetch + ff-only pull + 失败告警。

**关键原则**（SOUL 铁律）：
- **不**写 `print("OK")` 不检查 returncode
- **不**在脚本里 push（这次纯本地）
- **不**操作孤儿目录 `C:\Users\86571\ai-news-radar\`

**核心流程**：
1. 路径辨识：`Test-Path .git` 必须 True（铁律）
2. `git fetch origin master` → 检查 returncode
3. `git pull --ff-only origin master` → 检查 returncode（非 fast-forward 即报警，**禁止** `--rebase` 或 `--hard`）
4. drift 检查：对比本地 HEAD 与 origin/master 的 commit 差
5. 输出结构化结果（OK / WARN drift=N / FAIL）

### 3.2 触发机制

**选项 1（推荐）**：独立 cron，每 6 小时跑一次
- 时间窗：06:00 / 12:00 / 18:00 / 24:00 CST（避开工作时段峰值）
- 用 OpenClaw cron 或 Windows Task Scheduler

**选项 2**：挂在现有 9:35 管家 cron 后面
- 优点：少一个 cron
- 缺点：变成一天一次，万一今天没开电脑就过期了

**建议**：先用**选项 2**（最低成本），Jack 觉得不够再加 **选项 1**。

### 3.3 验证 / 报警手段

- 脚本末尾输出 JSON：
  ```json
  {
    "ts": "2026-06-15T13:30:00+08:00",
    "local_sha": "0f3214e...",
    "origin_sha": "0f3214e...",
    "drift_commits": 0,
    "status": "OK"
  }
  ```
- drift > 10：WARN（黄色，提醒但不阻塞）
- drift > 50：FAIL（红色，强制 Jack 注意）

---

## 4. 方案 B 简述（备用）

改 `radar-watchdog.yml`：在 health.json 输出里加一个字段 `local_drift_estimate`（基于 origin/master commit 时间戳推算 Jack 本地落后多久）。

**优点**：让 Jack 打开 health.json 就知道落后多少。
**缺点**：仍然被动。Jack 必须自己 fetch 才能消除 drift。

**适用场景**：如果 Jack 不愿意挂 cron，至少 health.json 能给个数字提示。

---

## 5. 方案 C 简述（不推荐）

维持现状，Jack 主动 `git fetch && git pull` 一次性同步。

**优点**：0 成本。
**缺点**：每次都要手敲，必然忘。6-15 就是这个模式的必然结果。

---

## 6. 落地状态（本轮）

- ✅ 拉平本地到 origin/master（drift = 0）
- ✅ 写 `scripts/local_sync.ps1`
- ✅ 写 `scripts/check_local_drift.ps1`（沙盒检查，**不修改任何状态**）
- ✅ 写本文档
- ⏸ cron 配置：待 Jack 拍板时间窗

---

## 7. Jack 拍板项

1. **cron 时间窗**：
   - 6/12/18/24 CST 每 6h？
   - 只挂凌晨（02:00 / 08:00）？
   - 跟现有 9:35 管家 cron 合并？

2. **drift 报警阈值**：
   - 10 commit WARN / 50 commit FAIL？
   - 还是用时间（> 4h 报警）？

3. **失败处理**：
   - 脚本 FAIL 时发 webhook？
   - 还是只写日志，Jack 每天扫一次？

---

## 8. 不要忘记

- 铁律：真 working tree = `C:\Users\86571\ai-news-radar-gh`
- 孤儿目录 `C:\Users\86571\ai-news-radar\` **禁止操作**
- 6-11 P0 修复：watchdog `fetch-depth: 0` 已落（commit 03ef804）
- 三层凭证：gh keyring / Windows Credential Manager / OAuth 浏览器

---

## 9. 6-15 复盘追加：前端"上次更新时间"硬指标（方案 4）

**背景**：6-15 13:24 CST 卡死事件暴露——用户**无法一眼判断**"数据是不是新鲜"。

### 9.1 当前现状

`index.html` 渲染逻辑（基于 `data/latest-24h-min.json`）：

```javascript
// 现有逻辑(从 app.js 推断,需要实测确认)
const res = await fetch('./data/latest-24h-min.json');
const data = await res.json();
const lastUpdate = new Date(data.generated_at);
const formatted = lastUpdate.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
document.getElementById('last-update').textContent = `数据更新: ${formatted}`;
```

**问题**：只显示文字，无视觉警告。6-15 卡死时用户看到的是 `数据更新: 2026/6/15 08:17`——但需要**主动对比当前时间**才能意识到"这是 5 小时前"。

### 9.2 改进方案：3 段视觉警告

```javascript
// 改进版伪代码
async function renderLastUpdate() {
    try {
        const res = await fetch('./data/latest-24h-min.json', { cache: 'no-store' });
        const data = await res.json();
        const lastUpdate = new Date(data.generated_at);
        const now = new Date();
        const ageMin = Math.floor((now - lastUpdate) / 60000);

        const el = document.getElementById('last-update');
        el.textContent = `数据更新: ${formatTime(lastUpdate)}`;

        // 视觉警告
        el.classList.remove('fresh', 'warn', 'stale', 'broken');
        if (ageMin < 60) {
            el.classList.add('fresh');  // 绿色
        } else if (ageMin < 180) {
            el.classList.add('warn');   // 黄色
            el.textContent += ` ⚠️ 已滞后 ${Math.floor(ageMin / 60)} 小时`;
        } else {
            el.classList.add('broken'); // 红色
            el.textContent += ` 🚨 停滞 ${Math.floor(ageMin / 60)} 小时,雷达可能卡死`;
        }
    } catch (err) {
        const el = document.getElementById('last-update');
        el.classList.add('broken');
        el.textContent = '🚨 数据加载失败,雷达可能完全停摆';
    }
}

// 页面加载时跑一次,之后每 5 分钟刷新
renderLastUpdate();
setInterval(renderLastUpdate, 5 * 60 * 1000);
```

### 9.3 配套 CSS(在 index.html <style> 追加)

```css
#last-update.fresh { color: #28a745; }   /* 绿:< 1h */
#last-update.warn  { color: #ffc107; }   /* 黄:1h-3h */
#last-update.broken { 
    color: #dc3545; 
    font-weight: bold; 
    animation: pulse 2s infinite; 
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
```

### 9.4 阈值建议(可调)

| age 区间 | 颜色 | 含义 | 建议 |
|---|---|---|---|
| < 60min | 🟢 绿 | 健康 | 静默显示 |
| 60~180min | 🟡 黄 | 滞后 | 加 ⚠️ emoji + "已滞后 X 小时" |
| > 180min | 🔴 红 | 卡死 | 加 🚨 emoji + "停滞 X 小时" + 脉动动画 |
| 数据加载失败 | 🔴 红 | 故障 | "数据加载失败" + 脉动动画 |

### 9.5 阈值选择理由

- **60min (1h)**：正常情况每 30min 更新一次，1h 已算 1 次漏
- **180min (3h)**：6-15 静默 5h 远超此值,3h 是"明显异常"门槛
- **5min 刷新**：比 30min 更新频率高,用户停留页面时能及时看到状态变化

### 9.6 与其他方案的关系

- **方案 1（cron 错开）**：减少漏跑概率
- **方案 2（本地 watchdog）**：兜底自动恢复
- **方案 4（前端警告）**：用户能**立即感知**异常,即使后端还没救回

**三层防护**：预防 + 自动恢复 + 用户感知。即使前两层都失效,第三层也能让 Jack 立刻知道"雷达挂了"。

### 9.7 落地

- ⏸ 改 `app.js` / `index.html`——**等 Jack 拍板**
- 阈值 1h/3h 是建议,实际可调
- 样式参考 Bootstrap 颜色规范,可适配深色模式

---
