/**
 * opml_to_radar_json.js
 * Reads feeds/follow.opml → fetches each feed via curl → outputs data/latest-24h-min.json
 * in the same schema as update_news.py so score_injector_gh.js can process it.
 * 
 * Run from repo root: node scripts/opml_to_radar_json.js
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
  'arXiv Robotics': 'arXiv cs.RO',
  'arXiv Embodied AI': 'arXiv cs.AI',
  'TechCrunch Robotics': 'TechCrunch Robotics',
  '36kr': '36kr',
};

function decodeHtmlEntity(str) {
  return str.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

function parseOPML(xml) {
  const feeds = [];
  const outlineRe = /<outline([^>]+)>/gi;
  let m;
  while ((m = outlineRe.exec(xml)) !== null) {
    const attrs = m[1];
    const xmlUrlM = /xmlUrl="([^"]+)"/.exec(attrs);
    const titleM = /title="([^"]+)"/.exec(attrs);
    const textM = /text="([^"]+)"/.exec(attrs);
    if (!xmlUrlM) continue;
    const url = decodeHtmlEntity(xmlUrlM[1]);
    const title = decodeHtmlEntity(titleM ? titleM[1] : (textM ? textM[1] : '未知'));
    const text = decodeHtmlEntity(textM ? textM[1] : title);
    feeds.push({ url, title, text });
  }
  return feeds;
}

function curlFetch(url) {
  return new Promise((resolve) => {
    const curlCmd = process.platform === 'win32' ? 'curl.exe' : 'curl';
    const args = ['--connect-timeout', '12', '-L', '-s', url];
    if (PROXY) {
      if (process.platform === 'win32') {
        args.unshift('-x', PROXY);
      } else {
        args.unshift('--proxy', PROXY);
      }
    }
    const child = spawn(curlCmd, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let d = '';
    const timer = setTimeout(() => { child.kill(); resolve(''); }, 20000);
    child.stdout.on('data', (c) => { d += c; });
    child.on('error', () => { clearTimeout(timer); resolve(''); });
    child.on('close', () => { clearTimeout(timer); resolve(d); });
  });
}

function parseRSS(xml, source) {
  if (!xml || xml.length < 50) return [];
  const items = [];
  const itemRe = /<item>([\s\S]*?)<\/item>/gi;
  let m;
  while ((m = itemRe.exec(xml)) !== null) {
    const b = m[1];
    function get(tag) {
      const re = new RegExp('<' + tag + '[^>]*>([\\s\\S]*?)<\\/' + tag + '>', 'i');
      const m2 = b.match(re);
      return m2 ? m2[1].replace(/<[^>]+>/g, '').trim() : '';
    }
    const title = decodeHtmlEntity(get('title'));
    const link = decodeHtmlEntity(get('link') || get('guid'));
    const desc = decodeHtmlEntity(get('description') || get('summary') || get('content'));
    let pubDate = get('pubDate') || get('dc:date') || get('published');
    // Parse date
    let published_at = null;
    if (pubDate) {
      try {
        const d = new Date(pubDate);
        if (!isNaN(d)) published_at = d.toISOString();
      } catch(e) {}
    }
    if (!title || title.length < 6 || !link) continue;

    // Generate stable id from link
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
      title_en: null,
      title_zh: title,
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
  // Detect if it's HTML (failed fetch)
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

  // Deduplicate by id
  const seen = new Set();
  const deduped = [];
  for (const item of allItems) {
    if (!seen.has(item.id)) {
      seen.add(item.id);
      deduped.push(item);
    }
  }

  console.log(`Total items: ${allItems.length}, deduped: ${deduped.length}`);

  const output = {
    generated_at: new Date().toISOString(),
    window_hours: 24,
    total_items: deduped.length,
    total_items_ai_raw: deduped.length,
    total_items_raw: deduped.length,
    total_items_all_mode: deduped.length,
    topic_filter: 'robotics embodied humanoid BCI physical_ai',
    ai_relevance_threshold: 0.3,
    archive_total: 16460,
    site_count: feeds.length,
    source_count: feeds.length,
    site_stats: {},
    items: deduped,
    items_ai: deduped,
  };

  const outPath = path.join(__dirname, '..', 'data', 'latest-24h-min.json');
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2), 'utf8');
  console.log(`Written: ${outPath} (${deduped.length} items)`);
}

run().catch(e => { console.error(e); process.exit(1); });
