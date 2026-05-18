/**
 * opml_to_radar_json.js
 * Reads feeds/follow.opml → fetches each feed via curl → outputs data/latest-24h-min.json
 * in the same schema as update_news.py so score_injector_gh.js can process it.
 * 
 * Bilingual titles: title_en (original) + title_zh (Chinese translation via MyMemory API)
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PROXY = process.env.PROXY || '';
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

// Sources that provide Chinese titles natively (no translation needed)
const CHINESE_SOURCES = new Set(['36kr', '36Kr']);

/**
 * Translate text to Chinese using MyMemory free API.
 * Returns Chinese translation or null on failure.
 * Batches up to 5 titles per API call using langpair format.
 */
async function translateToChinese(texts) {
  if (!texts || texts.length === 0) return texts.map(() => null);

  const proxyArgs = PROXY ? ['-x', PROXY] : [];
  const textsToTranslate = texts.filter(t => t && t.length > 0 && t.length < 500);
  const results = new Array(texts.length).fill(null);

  // Fill in non-translatable slots
  texts.forEach((t, i) => {
    if (!t || t.length === 0 || t.length >= 500) results[i] = t;
  });

  // Translate in batches of 5
  const translatable = textsToTranslate.map((t, i) => ({ original: t, origIdx: texts.findIndex(ot => ot === t && ot === textsToTranslate[i]) })).filter(x => x.origIdx >= 0);

  for (let i = 0; i < translatable.length; i += 5) {
    const batch = translatable.slice(i, i + 5);
    const q = batch.map(t => t.original).join(' | ');
    const url = `https://api.mymemory.translated.net/get?q=${encodeURIComponent(q)}&langpair=en%7Czh-CN`;

    try {
      const args = [...proxyArgs, '-s', '-m', '5', '-o', '/dev/null', '-w', '%{http_code}', url];
      const proc = spawn('curl.exe', args);
      let output = '';
      proc.stdout.on('data', d => output += d);

      const code = await new Promise(resolve => {
        proc.on('close', c => resolve(c));
        setTimeout(() => { proc.kill(); resolve(999); }, 8000);
      });

      // Alternative: use curl to fetch and extract response directly
      const fetchArgs = [...proxyArgs, '-s', url];
      const fetchProc = spawn('curl.exe', fetchArgs);
      let response = '';
      fetchProc.stdout.on('data', d => response += d);

      const respCode = await new Promise(resolve => {
        fetchProc.on('close', c => resolve(c));
        setTimeout(() => { fetchProc.kill(); resolve(999); }, 8000);
      });

      if (respCode === 200 && response.length > 10) {
        try {
          const parsed = JSON.parse(response);
          const translatedText = parsed?.responseData?.translatedText;
          if (translatedText) {
            const parts = translatedText.split(' | ');
            batch.forEach((item, bi) => {
              if (results[item.origIdx] === null) {
                results[item.origIdx] = parts[bi]?.trim() || texts[item.origIdx];
              }
            });
          }
        } catch(e) {
          // JSON parse failed, try splitting by |
          const parts = response.split(' | ');
          batch.forEach((item, bi) => {
            if (results[item.origIdx] === null && parts[bi]) {
              results[item.origIdx] = parts[bi].trim();
            }
          });
        }
      }
    } catch(e) {
      // Translation failed, keep original title
    }

    // Rate limit: wait between batches
    if (i + 5 < translatable.length) await new Promise(r => setTimeout(r, 500));
  }

  return results;
}

// ── Expose translateToChinese so opml_rss_collector.js can reuse it ──
module.exports = { translateToChinese };

/* ─── Rest of script (standalone mode) ─── */

function parseOPML(xml) {
  const feeds = [];
  const re = /<outline[^>]+text="([^"]*)"[^>]+xmlUrl="([^"]*)"[^>]*>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    feeds.push({ title: m[1], url: m[2] });
  }
  // Also handle outline with title attr
  const re2 = /<outline[^>]+title="([^"]*)"[^>]+xmlUrl="([^"]*)"[^>]*>/g;
  while ((m = re2.exec(xml)) !== null) {
    if (!feeds.find(f => f.url === m[2])) feeds.push({ title: m[1], url: m[2] });
  }
  return feeds;
}

function curlFetch(url) {
  return new Promise((resolve) => {
    const proxyArgs = PROXY ? ['-x', PROXY] : [];
    const args = [...proxyArgs, '-s', '-L', '--max-time', '20', '-o', '-', url];
    const proc = spawn('curl.exe', args);
    let data = '';
    proc.stdout.on('data', d => data += d);
    proc.on('close', () => resolve(data));
    proc.on('error', () => resolve(''));
    setTimeout(() => { proc.kill(); resolve(''); }, 25000);
  });
}

function parseRSS(xml, source) {
  const items = [];
  const itemMatches = xml.matchAll(/<item>([\s\S]*?)<\/item>/g);
  for (const match of itemMatches) {
    const itemXml = match[1];
    const get = (tag) => {
      const m = itemXml.match(new RegExp(`<${tag}[^>]*><!\[CDATA\[([\s\S]*?)\]\]><\/${tag}>`));
      if (m) return m[1].trim();
      const m2 = itemXml.match(new RegExp(`<${tag}[^>]*>([\s\S]*?)<\/${tag}>`));
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
      title_en: title,  // Store original English title
      title_zh: null,  // Will be translated after collection
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
  const xml = await curlFetch(feed.url);
  if (!xml || xml.length < 100) return [];
  if (xml.trim().startsWith('<!') || xml.trim().startsWith('<html')) return [];
  const items = parseRSS(xml, feed.text || feed.title);
  return items;
}

async function run() {
  const opmlPath = path.join(__dirname, '..', 'feeds', 'follow.opml');
  const opmlXml = fs.readFileSync(opmlPath, 'utf8');
  const feeds = parseOPML(opmlXml);
  console.log(`OPML: ${feeds.length} feeds found`);

  const allItems = [];
  const batchSize = 4;
  for (let i = 0; i < feeds.length; i += batchSize) {
    const batch = feeds.slice(i, i + batchSize);
    console.log(`[Batch ${i/batchSize + 1}/${Math.ceil(feeds.length/batchSize)}] fetching ${batch.length} feeds...`);
    const results = await Promise.all(batch.map(f => fetchFeed(f)));
    for (const items of results) {
      allItems.push(...items);
    }
    if (i + batchSize < feeds.length) await new Promise(r => setTimeout(r, 1000));
  }

  console.log(`Collected ${allItems.length} raw items`);
  fs.writeFileSync(path.join(__dirname, '..', 'data', `raw_${Date.now()}.json`), JSON.stringify(allItems, null, 2));

  // ── Translate non-Chinese titles ──
  console.log('Translating titles to Chinese...');
  const nonZhSources = Object.keys(SITE_NAME_MAP).filter(s => !CHINESE_SOURCES.has(s));
  const translateItems = allItems.filter(item => nonZhSources.some(s => item.site_name?.includes(SITE_NAME_MAP[s] || s)));

  // Batch translate in groups of 5
  const BATCH = 5;
  let translated = 0;
  for (let i = 0; i < translateItems.length; i += BATCH) {
    const batch = translateItems.slice(i, i + BATCH);
    const titles = batch.map(item => item.title);
    const zhTitles = await translateToChinese(titles);
    batch.forEach((item, bi) => {
      item.title_zh = zhTitles[bi] || item.title;
    });
    translated += batch.length;
    process.stdout.write(`\r  Translated ${translated}/${translateItems.length}...`);
    if (i + BATCH < translateItems.length) await new Promise(r => setTimeout(r, 600));
  }
  console.log(`\nDone translating ${translated} titles`);

  // Deduplicate by id
  const seen = new Set();
  const deduped = allItems.filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
  console.log(`Deduplicated: ${allItems.length} → ${deduped.length}`);

  const result = {
    generated_at: new Date().toISOString(),
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

  const outPath = path.join(__dirname, '..', 'data', 'latest-24h-min.json');
  fs.writeFileSync(outPath, JSON.stringify(result));
  console.log(`Written ${deduped.length} items to ${outPath}`);
}

run().catch(console.error);
