#!/usr/bin/env node
/**
 * score_injector_gh.js
 * GitHub Actions 版本：将五维评分注入 latest-24h-min.json
 * 运行于 GitHub Actions runner，注入后文件被 git commit + Pages artifact 使用
 */
const https = require('https');
const fs = require('fs');
const path = require('path');

// ===== 配置 =====
const GP = 'https://jackliu-teadrinker.github.io/ai-news-radar/data';
const TARGET_DATE = process.env.TARGET_DATE || new Date().toISOString().slice(0, 10);
const GITHUB_TOKEN = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || '';
const REPO_OWNER = 'Jackliu-teadrinker';
const REPO_NAME = 'ai-news-radar';
const CLASSIFIED_JSON_DATE = path.join(__dirname, '..', 'data', TARGET_DATE + '-classified.json');
const CLASSIFIED_JSON_FALLBACK = path.join(__dirname, '..', 'data', 'classified.json');
const CLASSIFIED_JSON = fs.existsSync(CLASSIFIED_JSON_DATE) ? CLASSIFIED_JSON_DATE : (fs.existsSync(CLASSIFIED_JSON_FALLBACK) ? CLASSIFIED_JSON_FALLBACK : CLASSIFIED_JSON_DATE);

// ===== 工具函数 =====
function httpGet(url, timeoutMs) {
  return new Promise((res, rej) => {
    const req = https.get(url, { headers: { 'User-Agent': 'openclaw-score', 'Accept': 'application/json' } }, (r) => {
      if (r.statusCode >= 400) { rej(new Error(`HTTP ${r.statusCode}`)); return; }
      let d = ''; r.on('data', c => d += c); r.on('end', () => res(d));
    });
    req.on('error', rej);
    req.setTimeout(timeoutMs || 15000, () => { req.destroy(); rej(new Error('timeout')); });
  });
}

function apiRequest(method, apiPath, data) {
  return new Promise((res, rej) => {
    const body = data ? JSON.stringify(data) : undefined;
    const opts = {
      hostname: 'api.github.com', path: apiPath, method,
      headers: { 'Authorization': `Bearer ${GITHUB_TOKEN}`, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'openclaw-score' }
    };
    if (body) opts.headers['Content-Length'] = Buffer.byteLength(body);
    const req = https.request(opts, (r) => {
      let d = ''; r.on('data', c => d += c); r.on('end', () => {
        try { res({ s: r.statusCode, d: JSON.parse(d) }); }
        catch { res({ s: r.statusCode, d }); }
      });
    });
    req.on('error', rej);
    if (body) req.write(body);
    req.end();
  });
}

function calcTimeliness(pubDateStr) {
  if (!pubDateStr) return 5;
  try {
    const ms = new Date(pubDateStr).getTime();
    const hoursAgo = (Date.now() - ms) / 3600000;
    return Math.max(0, Math.round(15 - hoursAgo * 0.6));
  } catch { return 5; }
}

const DOMAIN_AUTH = {
  'arxiv.org': 20, 'nature.com': 20, 'science.org': 19, 'spectrum.ieee.org': 18,
  'techcrunch.com': 16, 'therobotreport.com': 15, 'jiqizhixin.com': 15,
  'latepost.com': 15, 'zhidx.com': 14, '36kr.com': 14, 'qbitai.com': 14,
  'neuralink.com': 19, 'bostondynamics.com': 17, 'unitree.com': 19,
  'tesla.com': 20, 'figure.ai': 20, 'nvidia.com': 18, 'deepmind.google': 18,
};
function getDomainAuthority(domain) {
  if (!domain) return 8;
  const d = domain.replace(/^www\./, '').toLowerCase();
  return DOMAIN_AUTH[d] !== undefined ? DOMAIN_AUTH[d] : 8;
}

function urlToKey(url) {
  try {
    const u = new URL(url);
    const gn = u.searchParams.get('url');
    if (gn) {
      try { const gnu = new URL(gn); return (gnu.hostname.replace(/^www\./, '') + gnu.pathname).toLowerCase(); }
      catch { return u.hostname.replace(/^www\./, '') + u.pathname; }
    }
    return u.hostname.replace(/^www\./, '') + u.pathname;
  } catch { return (url || '').slice(0, 80).toLowerCase(); }
}

function normTitle(t) { return (t || '').toLowerCase().replace(/[''""'']/g, '').replace(/\s+/g, ' ').trim().slice(0, 80); }

// ===== 评分注入 =====
async function main() {
  console.log('[SI-GH] 开始评分注入...');
  if (!GITHUB_TOKEN) { console.error('[SI-GH] 警告: GITHUB_TOKEN 未设置，跳过 GitHub API 操作（评分注入继续）'); }
  // 如果 classified.json 不存在，优雅退出不阻塞 workflow
  if (!fs.existsSync(CLASSIFIED_JSON)) {
    console.log('[SI-GH] classified.json 不存在，跳过评分注入（本地 pipeline 未运行）');
    process.exit(0);
  }
  const classified = JSON.parse(fs.readFileSync(CLASSIFIED_JSON, 'utf8'));
  console.log('[SI-GH] classified.json:', Object.keys(classified).length, '条');

  // 构建查找表
  const byUrl = {}, byNorm = {};
  for (const title in classified) {
    const info = classified[title];
    if (info._url) { const k = urlToKey(info._url); if (k) byUrl[k] = info; }
    byNorm[normTitle(title)] = info;
  }

  // 从 GitHub Pages 拉取 JSON
  let data24h = null, data24hMin = null;
  try {
    data24hMin = JSON.parse(await httpGet(`${GP}/latest-24h-min.json`, 15000));
    console.log('[SI-GH] latest-24h-min.json:', (data24hMin.items_ai || []).length, 'items_ai');
  } catch (e) { console.error('[SI-GH] 获取 latest-24h-min.json 失败:', e.message); }

  // 注入分数到 items_ai
  if (data24hMin && data24hMin.items_ai) {
    let scored = 0, already = 0;
    const FIELDS = ['category', 'core_fact', 'importance', 'relevance', 'authority', 'depth', 'timeliness', 'writing_value', 'total_score'];
    for (const item of data24hMin.items_ai) {
      const urlKey = urlToKey(item.url || '');
      const titleKey = normTitle(item.title_zh || item.title || '');
      const info = (urlKey && byUrl[urlKey]) ? byUrl[urlKey] : (titleKey && byNorm[titleKey] ? byNorm[titleKey] : null);
      if (info) {
        if (info.total_score !== undefined && info.total_score !== null) { already++; }
        else {
          for (const k of FIELDS) { if (info[k] !== undefined) item[k] = info[k]; }
          // 兜底：没有分数的用默认值
          if (item.total_score === undefined) {
            item.relevance = item.relevance || 15;
            item.authority = item.authority || getDomainAuthority(item.url || '');
            item.depth = item.depth || 12;
            item.timeliness = item.timeliness || calcTimeliness(item.published_at);
            item.writing_value = item.writing_value || 3;
            item.total_score = item.total_score || 48;
            item.category = item.category || 'general_robot';
          }
          scored++;
        }
      } else {
        // 完全未匹配的用默认值
        item.relevance = 15;
        item.authority = getDomainAuthority(item.url || '');
        item.depth = 12;
        item.timeliness = calcTimeliness(item.published_at);
        item.writing_value = 3;
        item.total_score = 48;
        item.category = 'general_robot';
        scored++;
      }
    }
    console.log('[SI-GH] 注入完成: 新注入', scored, '条, 已有分', already, '条');
    // 写回本地文件
    fs.writeFileSync(path.join(__dirname, '..', 'data', 'latest-24h-min.json'), JSON.stringify(data24hMin));
    console.log('[SI-GH] latest-24h-min.json 已更新');
  }
}

main().catch(e => { console.error('[SI-GH] 错误（不阻断 workflow）:', e.message); process.exit(0); });
