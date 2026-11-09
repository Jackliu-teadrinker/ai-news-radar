/**
 * radar-watchdog — 雷达外部哨兵（Cloudflare Worker Cron）
 *
 * 2026-11-09 立：GitHub 以「fork 仓库 Actions 用量规模过大」为由整体停掉了
 * ai-news-radar 的 Actions，仓库内的 keeper.yml 因此和业务一起静默 51 小时，
 * 站点数据冻结在 2026-11-06T23:50Z 无人知晓。教训是：哨兵不能和业务跑在同一条链上。
 *
 * 本 Worker 不在 GitHub 上跑，检查三件事：
 *   1. Pages 数据的 generated_at 年龄（数据有没有真的更新）
 *   2. dispatch 探针（Actions 是否被停：这就是 422 的来源）
 *   3. 超过阈值就报警（ALERT_WEBHOOK_URL），并尽量自救（GH_PAT 再补一刀 dispatch）
 *
 * 环境变量（wrangler secret put）：
 *   GH_PAT              fine-grained PAT，权限 Actions: write，仓库 ai-news-radar
 *   ALERT_WEBHOOK_URL   可选，任意接受 POST {"text": "..."} 的 webhook（企业微信/飞书/Telegram 中转）
 *   CHECK_TOKEN         可选，/check 端点的手动触发口令
 *   SITE_DATA_URL       可选，默认指向下面的 Pages 数据文件
 */

const DEFAULTS = {
  SITE_DATA_URL: "https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json",
  REPO: "Jackliu-teadrinker/ai-news-radar",
  WORKFLOW: "update-news.yml",
  BRANCH: "master",
};

// 数据年龄阈值（分钟）
const WARN_MIN = 90;   // 90 分钟没更新就该看一眼
const CRIT_MIN = 180;  // 3 小时没更新 = 流水线大概率死了

async function readAge(env) {
  const url = `${env.SITE_DATA_URL || DEFAULTS.SITE_DATA_URL}?cb=${Date.now()}`;
  const res = await fetch(url, {
    headers: { "User-Agent": "radar-watchdog/1.0", "Cache-Control": "no-cache" },
  });
  if (!res.ok) return { ok: false, status: res.status, ageMin: Infinity, generatedAt: null };
  const data = await res.json();
  const generatedAt = data.generated_at || null;
  if (!generatedAt) return { ok: false, status: 200, ageMin: Infinity, generatedAt: null };
  const ageMin = (Date.now() - Date.parse(generatedAt)) / 60000;
  return { ok: true, status: 200, ageMin, generatedAt, totalItems: data.total_items ?? null };
}

async function dispatch(env) {
  const repo = env.REPO || DEFAULTS.REPO;
  const workflow = env.WORKFLOW || DEFAULTS.WORKFLOW;
  const res = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_PAT}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "radar-watchdog/1.0",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: env.BRANCH || DEFAULTS.BRANCH }),
    }
  );
  const text = await res.text();
  return { status: res.status, accepted: res.status === 204, body: text.slice(0, 300) };
}

async function alert(env, level, message) {
  const payload = { text: `[radar-watchdog][${level}] ${message}`, level, ts: new Date().toISOString() };
  console.log(JSON.stringify(payload));
  if (!env.ALERT_WEBHOOK_URL) return;
  try {
    await fetch(env.ALERT_WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.log(`[alert] webhook failed: ${e}`);
  }
}

async function runCheck(env, { allowDispatch = true } = {}) {
  const fresh = await readAge(env);
  const report = {
    generatedAt: fresh.generatedAt,
    ageMin: Number.isFinite(fresh.ageMin) ? Math.round(fresh.ageMin) : null,
    totalItems: fresh.totalItems ?? null,
    level: "ok",
    actions: [],
  };

  if (!fresh.ok) {
    report.level = "crit";
    report.actions.push(`pages_fetch_failed(${fresh.status})`);
    await alert(env, "CRIT", `Pages 数据取不到（HTTP ${fresh.status}），站点可能整体挂了`);
    return report;
  }

  if (fresh.ageMin <= WARN_MIN) return report;

  report.level = fresh.ageMin > CRIT_MIN ? "crit" : "warn";
  report.actions.push(`stale_${report.ageMin}min`);

  // 自救：补一刀 dispatch。422 就直接说明 Actions 被停，这正是 11-06 的情形。
  if (allowDispatch && env.GH_PAT) {
    const d = await dispatch(env);
    report.dispatch = d;
    if (d.accepted) {
      report.actions.push("dispatch_ok");
    } else if (d.status === 422 && /disabled/i.test(d.body)) {
      report.level = "crit";
      report.actions.push("actions_disabled");
      await alert(
        env,
        "CRIT",
        `GitHub Actions 已被停用（422），站点数据停在 ${fresh.generatedAt}。` +
          `去 https://github.com/${env.REPO || DEFAULTS.REPO}/actions 点 re-enable 才会恢复`
      );
      return report;
    } else {
      report.actions.push(`dispatch_failed(${d.status})`);
    }
  }

  await alert(
    env,
    report.level.toUpperCase(),
    `数据已 ${report.ageMin} 分钟未更新（generated_at=${fresh.generatedAt}，共 ${fresh.totalItems ?? "?"} 条）`
  );
  return report;
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runCheck(env));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/check") {
      if (env.CHECK_TOKEN && url.searchParams.get("token") !== env.CHECK_TOKEN) {
        return new Response(JSON.stringify({ error: "bad token" }), { status: 403 });
      }
      const allowDispatch = url.searchParams.get("dispatch") !== "0";
      const report = await runCheck(env, { allowDispatch });
      return new Response(JSON.stringify(report, null, 2), {
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    return new Response("radar-watchdog up. GET /check", { status: 200 });
  },
};
