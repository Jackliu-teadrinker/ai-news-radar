/**
 * opml_to_radar_json.js - 增量版（跨平台）
 *
 * 策略：读取已有 latest-24h-min.json → 抓取所有feeds最新items → 只合并24h内新items → 追加写入
 * - 跨平台：Windows (curl.exe) 和 Linux (Node.js native http)
 * - 增量追加，不全量覆盖
 * - 自动清理超过24h的旧items
 *
 * Windows用法: node opml_to_radar_json.js
 * Linux/GitHub Actions用法: node opml_to_radar_json.js
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const https = require('https');
const http = require('http');

// ── 跨平台HTTP请求 ──
function httpGet(url, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const isHttps = url.startsWith('https://');
    const mod = isHttps ? https : http;
    const opts = {
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; radar-bot/1.0)',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        'Accept-Encoding': 'gzip, deflate',
      },
      timeout: timeoutMs,
    };
    const req = mod.get(url, opts, (res) => {
      if (res.statusCode >= 400) { res.resume(); resolve(''); return; }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    });
    req.on('error', () => resolve(''));
    req.on('timeout', () => { req.destroy(); resolve(''); });
  });
}

const PROXY = process.env.PROXY || '';
const DATA_DIR  = path.join(__dirname, '..', 'data');
const OPML_DIR = path.join(__dirname, '..', 'feeds');
const MIN_FILE = path.join(DATA_DIR, 'latest-24h-min.json');

const GN_LABEL_MAP = {
  'GN: 人形机器人': 'humanoid',
  'GN: 具身智能': 'embodied_ai',
  'GN: 脑机接口': 'brain_computer',
  'GN: Physical AI': 'physical_ai',
  'arXiv Robotics': 'robotics',
  'arXiv Embodied AI': 'robotics',
  'TechCrunch Robotics': 'robotics',
  '36kr': 'robotics',
};

const SITE_NAME_MAP = {
  'GN: 人形机器人': 'Google News (Humanoid Robot)',
  'GN: 具身智能': 'Google News (Embodied AI)',
  'GN: 脑机接口': 'Google News (BCI)',
  'GN: Physical AI': 'Google News (Physical AI)',
  'arXiv Robotics': 'arXiv Robotics (cs.RO)',
  'arXiv Embodied AI': 'arXiv Embodied AI (cs.AI)',
  'TechCrunch Robotics': 'TechCrunch Robotics',
  '36kr': '36Kr',
};

const CHINESE_SOURCES = new Set(['36kr', '36Kr']);

// ── 增量相关常量 ──
const WINDOW_MS = 24 * 3600 * 1000;
const MAX_ITEMS = 500;

// ── MyMemory翻译（跨平台，Node.js原生） ──
async function translateToChinese(texts) {
  if (!texts || texts.length === 0) return texts.map(() => null);
  const results = new Array(texts.length).fill(null);
  const textsToTranslate = texts
    .map((t, i) => ({ t, i }))
    .filter(x => x.t && x.t.length > 0 && x.t.length < 500);

  texts.forEach((t, i) => {
    if (!t || t.length === 0 || t.length >= 500) results[i] = t;
  });

  for (let i = 0; i < textsToTranslate.length; i += 5) {
    const batch = textsToTranslate.slice(i, i + 5);
    const q = batch.map(x => x.t).join(' | ');
    const url = `https://api.mymemory.translated.net/get?q=${encodeURIComponent(q)}&langpair=en%7Czh-CN`;
    try {
      const response = await httpGet(url, 8000);
      if (response && response.length > 10) {
        try {
          const parsed = JSON.parse(response);
          const translatedText = parsed?.responseData?.translatedText;
          if (translatedText) {
            const parts = translatedText.split(' | ');
            batch.forEach((item, bi) => {
              if (results[item.i] === null) {
                results[item.i] = parts[bi]?.trim() || texts[item.i];
              }
            });
          }
        } catch(e) {
          const parts = response.split(' | ');
          batch.forEach((item, bi) => {
            if (results[item.i] === null && parts[bi]) {
              results[item.i] = parts[bi].trim();
            }
          });
        }
      }
    } catch(e) {}
    if (i + 5 < textsToTranslate.length) await new Promise(r => setTimeout(r, 500));
  }
  return results;
}

function parseOPML(xml) {
  const feeds = [];
  const re = /<outline[^>]+text="([^"]*)"[^>]+xmlUrl="([^"]*)"[^>]*>/g;
  let m;
  while ((m = re.exec(xml)) !== null) feeds.push({ title: m[1], url: m[2] });
  const re2 = /<outline[^>]+title="([^"]*)"[^>]+xmlUrl="([^"]*)"[^>]*>/g;
  while ((m = re2.exec(xml)) !== null) {
    if (!feeds.find(f => f.url === m[2])) feeds.push({ title: m[1], url: m[2] });
  }
  return feeds;
}

function parseRSS(xml, source) {
  const items = [];
  const itemMatches = xml.matchAll(/<item>([\s\S]*?)<\/item>/g);
  for (const match of itemMatches) {
    const itemXml = match[1];
    const get = (tag) => {
      const cdataStart = '<![CDATA[';
      const csIdx = itemXml.indexOf(cdataStart);
      if (csIdx >= 0) {
        const ceIdx = itemXml.indexOf(']]>', csIdx + cdataStart.length);
        if (ceIdx >= 0) return itemXml.substring(csIdx + cdataStart.length, ceIdx).trim();
      }
      const m2 = itemXml.match(new RegExp('<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>'));
      return m2 ? m2[1].replace(/<[^>]+>/g, '').trim() : '';
    };
    const title = get('title');
    const link = get('link');
    let published_at = '';
    const pubMatch = itemXml.match(/<pubDate>([\s\S]*?)<\/pubDate>/);
    if (pubMatch) {
      try { published_at = new Date(pubMatch[1]).toISOString(); } catch(e) {}
    }
    if (!title || title.length < 6 || !link) continue;
    const id = crypto.createHash('sha1').update(link).digest('hex').substring(0, 32);
    const siteName = SITE_NAME_MAP[source] || source;
    const aiLabel = GN_LABEL_MAP[source] || 'robotics';

    items.push({
      id,
      site_id: source.replace(/[^a-zA-Z0-9]/g, '_').substring(0, 20),
      site_name: siteName,
      source: siteName,
      title,
      url: link,
      published_at: published_at || new Date().toISOString(),
      ai_score: 0.5,
      ai_label: aiLabel,
      title_en: title,
      title_zh: null,
      category: null,
      gn_label: null,
      relevance: 20,
      authority: 15,
      depth: 10,
      timeliness: 20,
      writing_value: 5,
      total_score: 70,
    });
  }
  return items;
}

async function fetchFeed(feed) {
  const xml = await httpGet(feed.url, 20000);
  if (!xml || xml.length < 100) return [];
  if (xml.trim().startsWith('<!') || xml.trim().startsWith('<html')) return [];
  const items = parseRSS(xml, feed.text || feed.title);
  return items;
}

// ── 增量合并 ──
function mergeItems(existingItems, newItems, windowMs) {
  const now = Date.now();
  const existingIds = new Set(existingItems.map(i => i.id));

  // 过滤已有items：只保留24h内的
  const retained = existingItems.filter(item => {
    const itemTime = new Date(item.published_at || item.first_seen_at || 0).getTime();
    return (now - itemTime) < windowMs;
  });

  // 合并新items（去重）
  const added = newItems.filter(item => {
    const itemTime = new Date(item.published_at || 0).getTime();
    if ((now - itemTime) >= windowMs) return false;
    if (existingIds.has(item.id)) return false;
    return true;
  });

  const merged = [...retained, ...added];

  // 按时间倒序，保留最新MAX_ITEMS条
  merged.sort((a, b) => {
    const ta = new Date(a.published_at || 0).getTime();
    const tb = new Date(b.published_at || 0).getTime();
    return tb - ta;
  });

  return merged.slice(0, MAX_ITEMS);
}

// ── 主程序 ──
async function run() {
  const opmlPath = path.join(OPML_DIR, 'follow.opml');
  const opmlXml = fs.readFileSync(opmlPath, 'utf8');
  const feeds = parseOPML(opmlXml);
  console.log(`[增量采集] feeds: ${feeds.length} | window: 24h | max: ${MAX_ITEMS}`);

  // 读取已有数据
  let existingItems = [];
  let existingMeta = {};
  if (fs.existsSync(MIN_FILE)) {
    try {
      const existing = JSON.parse(fs.readFileSync(MIN_FILE, 'utf8'));
      existingItems = existing.items || existing.items_ai || [];
      existingMeta = { generated_at: existing.generated_at, total_items: existingItems.length };
      console.log(`  已有 ${existingItems.length} 条`);
    } catch(e) {
      console.log('  已有文件损坏或为空，将重新初始化');
    }
  } else {
    console.log('  无历史文件，初始化新数据集');
  }

  // 抓取所有feeds
  const allNewItems = [];
  const batchSize = 4;
  for (let i = 0; i < feeds.length; i += batchSize) {
    const batch = feeds.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;
    process.stdout.write(`\r  [${batchNum}/${Math.ceil(feeds.length/batchSize)}] fetching...`);
    const results = await Promise.all(batch.map(f => fetchFeed(f)));
    for (const items of results) allNewItems.push(...items);
    if (i + batchSize < feeds.length) await new Promise(r => setTimeout(r, 800));
  }
  console.log(`\n  抓取完成: ${allNewItems.length} 条`);

  if (allNewItems.length === 0) {
    console.log('[警告] 所有feeds返回0条，检查网络');
  }

  // 翻译非中文标题
  const nonZhItems = allNewItems.filter(item => !CHINESE_SOURCES.has(item.site_name));
  if (nonZhItems.length > 0) {
    console.log(`  翻译 ${nonZhItems.length} 条英文标题...`);
    const BATCH = 5;
    for (let i = 0; i < nonZhItems.length; i += BATCH) {
      const batch = nonZhItems.slice(i, i + BATCH);
      const titles = batch.map(item => item.title);
      const zhTitles = await translateToChinese(titles);
      batch.forEach((item, bi) => {
        item.title_zh = zhTitles[bi] || item.title;
      });
      if (i + BATCH < nonZhItems.length) await new Promise(r => setTimeout(r, 600));
    }
  }

  // 增量合并
  const merged = mergeItems(existingItems, allNewItems, WINDOW_MS);
  console.log(`  合并: ${existingItems.length} 已有 + ${allNewItems.length} 新 → ${merged.length} 最终`);

  // 去重
  const seen = new Set();
  const deduped = merged.filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });

  deduped.sort((a, b) => {
    const ta = new Date(b.published_at || 0).getTime();
    const tb = new Date(a.published_at || 0).getTime();
    return ta - tb;
  });

  const now = new Date().toISOString();
  const result = {
    generated_at: now,
    window_hours: 24,
    total_items: deduped.length,
    total_items_ai_raw: deduped.length,
    total_items_raw: deduped.length,
    total_items_all_mode: deduped.length,
    site_count: new Set(deduped.map(i => i.site_id)).size,
    source_count: new Set(deduped.map(i => i.source)).size,
    site_stats: {},
    items: deduped,
    items_ai: deduped,
  };

  fs.writeFileSync(MIN_FILE, JSON.stringify(result, null, 2), 'utf8');
  console.log(`\n[OK] 写入 ${deduped.length} 条 → ${MIN_FILE}`);
  console.log(`     更新时间: ${now}`);

  const cats = {};
  deduped.forEach(i => { if (i.category) cats[i.category] = (cats[i.category]||0)+1; });
  if (Object.keys(cats).length > 0) {
    console.log('  GN分类:', cats);
  }
}

run().catch(console.error);
