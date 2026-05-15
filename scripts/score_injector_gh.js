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

  // 优先读本地文件（workflow 中 Update data 步骤已更新），否则从 GitHub Pages 拉取
  let data24hMin = null;
  const localPath = path.join(__dirname, '..', 'data', 'latest-24h-min.json');
  if (fs.existsSync(localPath)) {
    try {
      data24hMin = JSON.parse(fs.readFileSync(localPath, 'utf8'));
      console.log('[SI-GH] loaded local latest-24h-min.json:', (data24hMin.items || data24hMin.items_ai || []).length, 'items');
    } catch (e) { console.error('[SI-GH] 读本地文件失败:', e.message); }
  }
  if (!data24hMin) {
    try {
      data24hMin = JSON.parse(await httpGet(`${GP}/latest-24h-min.json`, 15000));
      console.log('[SI-GH] loaded remote latest-24h-min.json:', (data24hMin.items || data24hMin.items_ai || []).length, 'items');
    } catch (e) { console.error('[SI-GH] 获取 remote latest-24h-min.json 失败:', e.message); }
  }

  // 获取 items 数组（OPML RSS 输出为 items，AI 过滤输出为 items_ai）
  const targetItems = data24hMin.items || data24hMin.items_ai || [];
  console.log('[SI-GH] items array:', targetItems.length);

  // 注入分数到 items
  if (targetItems.length > 0) {
    let scored = 0, already = 0;
    const FIELDS = ['category', 'core_fact', 'importance', 'relevance', 'authority', 'depth', 'timeliness', 'writing_value', 'total_score'];
    for (const item of targetItems) {
      // 如果已有 total_score 说明已注入，跳过
      if (item.total_score !== undefined && item.total_score !== null) { already++; continue; }

      // 优先用 classified.json 的评分数据（按 URL 或标题匹配）
      const urlKey = urlToKey(item.url || '');
      const titleKey = normTitle(item.title_zh || item.title || '');
      const info = (urlKey && byUrl[urlKey]) ? byUrl[urlKey] : (titleKey && byNorm[titleKey] ? byNorm[titleKey] : null);

      if (info) {
        for (const k of FIELDS) { if (info[k] !== undefined) item[k] = info[k]; }
      }

      // 兜底：没有任何分数的用默认值 + ai_score 基础分
      if (item.total_score === undefined || item.total_score === null) {
        const aiScore = item.ai_score || 0.5; // 0-1 浮点
        item.relevance     = item.relevance     || Math.round((aiScore) * 25 + 10);  // 10-35
        item.authority     = item.authority     || getDomainAuthority(item.url || '');
        item.depth         = item.depth         || 12;
        item.timeliness    = item.timeliness    || calcTimeliness(item.published_at);
        item.writing_value = item.writing_value || 3;
        item.total_score   = item.total_score   || Math.round(aiScore * 60 + 30);    // 30-90
        item.category      = item.category      || 'general_robot';
        scored++;
      } else {
        already++;
      }
    }
    console.log('[SI-GH] 注入完成: 新注入', scored, '条, 已有分', already, '条');
  }
  // 保存注入结果到本地文件
  const outPath = path.join(__dirname, '..', 'data', 'latest-24h-min.json');
  try {
    fs.writeFileSync(outPath, JSON.stringify(data24hMin, null, 2));
    console.log('[SI-GH] 已保存到', outPath, '文件大小:', fs.statSync(outPath).size, 'bytes');
  } catch (e) {
    console.error('[SI-GH] 写回文件失败:', e.message);
  }
}

main().catch(e => { console.error('[SI-GH] 错误（不阻断 workflow）:', e.message); process.exit(0); });
