// gn-proxy — Cloudflare Worker: 把 Google News RSS 抓取挪到边缘出口。
//
// 背景（2026-10-20）：GitHub Actions runner 是数据中心 IP，Google 对它限流，
// 一轮 GN 集体 503 把雷达打空（Bug #27）。本机住宅 IP 不受此限。
// 这个 Worker 跑在 Cloudflare 边缘（出口 IP 与 GitHub 云段不同），
// 上游 update_news.py 把 GN URL 前缀替换成本 Worker 地址即可绕行限流。
//
// 部署（Cf 账户零成本档够用）：
//   1. 建 Worker（Workers & Pages → Create Worker → 贴下面代码）。
//   2. 绑定一个子域名：radar-gn-proxy.<你的workers子域>.workers.dev
//   3. 把 base 写进 GitHub Actions secret：
//        GH secret: GN_PROXY_BASE_URL = https://radar-gn-proxy.<sub>.workers.dev
//   4. update-news.yml 的 env 加一行 GN_PROXY_BASE_URL: ${{ secrets.GN_PROXY_BASE_URL }}
//
// 路由：
//   GET /?q=robot&hl=en-US&gl=US&ceid=US:en&when=1d   → 透传到 Google News RSS
//   GET /gn?q=...                                        → 同上
// 返回：application/xml 的 Google News RSS（或 502/504 JSON 错误）。

const GOOGLE_NEWS_RSS = "https://news.google.com/rss/search";

// 边缘出口 UA：用一个稳定的、不被 Google 标记的桌面 UA。
// 注意：不要把 GitHub 的 UA 带进来（那正是被限流的特征）。
const EDGE_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

const CACHE_TTL_S = 300; // Google 自身缓存，边缘再叠 5min 降并发

// 白名单参数：只透传这些 query key，防下游塞任意参数。
const ALLOWED_PARAMS = new Set(["q", "hl", "gl", "ceid", "when", "num"]);

async function serveRss(req, url, env) {
  const q = url.searchParams.get("q");
  if (!q) {
    return jsonError(400, "missing required query param: q");
  }

  // 组装 Google News 查询（只带白名单参数）
  const gq = new URLSearchParams();
  ALLOWED_PARAMS.forEach((k) => {
    const v = url.searchParams.get(k);
    if (v !== null) gq.set(k, v);
  });
  gq.set("q", q); // 确保 q 在
  const target = `${GOOGLE_NEWS_RSS}?${gq.toString()}`;

  // 边缘缓存（命中直接回，不打下游）
  const cache = (env && env.CACHE) || caches.default;
  const cacheKey = new Request(target, { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) {
    return new Response(cached.body, {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "X-GN-Proxy": "cache-hit",
      },
    });
  }

  const up = await fetch(cacheKey, {
    headers: {
      "User-Agent": EDGE_UA,
      "Accept": "text/xml,application/xml,application/rss+xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
    },
  });

  if (!up.ok) {
    // 透传下游的 5xx/429，但带标识，方便上游判"这是 Google 又抖了"
    const body = await up.text();
    return jsonError(up.status === 429 ? 503 : 502, `google ${up.status}`, body);
  }

  const xml = await up.text();
  const resp = new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": `public, max-age=${CACHE_TTL_S}`,
      "X-GN-Proxy": "upstream-ok",
    },
  });
  // 存缓存（失败忽略，不影响主链路）
  try {
    await cache.put(cacheKey, resp.clone());
  } catch (_) { /* 缓存 best-effort */ }
  return resp;
}

function jsonError(code, msg, body) {
  return new Response(
    JSON.stringify({ error: msg, upstream_body_head: (body || "").slice(0, 200) }),
    { status: code, headers: { "Content-Type": "application/json" } },
  );
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    // 只放行 GET；其它方法 405
    if (req.method !== "GET") {
      return jsonError(405, "only GET supported");
    }
    // 允许 /?q= 或 /gn?q=
    return serveRss(req, url, env);
  },
};

// 健康检查（部署后 curl 这个应回 200 xml 或 502，而不是 404）
// curl "https://<你的worker域名>/?q=robot&hl=en-US&gl=US&ceid=US:en&when=1d"
