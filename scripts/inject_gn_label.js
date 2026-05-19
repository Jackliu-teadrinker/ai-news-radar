#!/usr/bin/env node
/**
 * inject_gn_label.js
 *
 * 策略：
 * 1. ai_label 直接映射（AI_LABEL_TO_GN）：robotics→Physical AI, humanoid→人形机器人 等
 * 2. classified.json 高质量 GN 标签（URL/title 精确匹配）
 * 3. 关键词模糊兜底（仅用于明显 robotics 相关的标题）
 *
 * 注意事项：
 * - RSS feeds 收集全网 AI 信号，并非专为 GN 设计
 * - 大部分 ai_general/ai_product_update 等不属于 GN 分类是正常现象
 * - 我们只给真正相关的项注入 GN category，宁缺毋滥
 */
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const CLASSIFIED = path.join(DATA_DIR, 'classified.json');
const LATEST24H  = path.join(DATA_DIR, 'latest-24h.json');
const OUTPUT     = LATEST24H;

const AI_LABEL_TO_GN = {
  robotics:       'GN: Physical AI',
  humanoid:       'GN: 人形机器人',
  embodied_ai:    'GN: 具身智能',
  brain_computer: 'GN: 脑机接口',
  physical_ai:    'GN: Physical AI',
};

const GN_KEYWORD_MAP = [
  {
    gn: 'GN: 人形机器人',
    kw: ['humanoid robot', 'humanoid:', '双足机器人', '全尺寸人形', 'unitree', 'figure ai',
         '宇树', '傅利叶智能', '智元机器人', '星动纪元', '逐际动力', '松延动力',
         '加速开拓者', '人形机器人', 'humanoid']
  },
  {
    gn: 'GN: 具身智能',
    kw: ['具身智能', 'embodied ai', '具身AI', 'VLA', '世界模型', '物理AI', 'physical ai',
         'manipulation', '灵巧手', '触觉', 'affordance']
  },
  {
    gn: 'GN: 脑机接口',
    kw: ['脑机接口', 'brain-computer', 'neuralink', '脑电', '思维控制', 'Neuralink',
         'Synchron', 'BrainGate', '脑电波']
  },
  {
    gn: 'GN: 机器人',
    kw: ['robot', 'robots', '机器人', '机械臂', '四足机器人', '协作机器人', 'cobot',
         '清洁机器人', '配送机器人', '手术机器人', 'service robot', 'industrial robot']
  },
  {
    gn: 'GN: Physical AI',
    kw: ['physical ai']
  },
];

function keywordGN(title) {
  const t = (title || '').toLowerCase();
  for (const { gn, kw } of GN_KEYWORD_MAP) {
    if (kw.some(k => t.includes(k.toLowerCase()))) return gn;
  }
  return null;
}

function extractGNFromKey(key) {
  if (!key || typeof key !== 'string') return null;
  const m = key.match(/[-–—\s]+GN:\s*(.+?)(?:\s*[-–—]|$)/);
  return m ? m[1].trim() : null;
}

function norm(s) {
  return (s || '').replace(/[^\w\u4e00-\u9fff]/g, '').toLowerCase();
}
function normUrl(url) {
  return (url || '').replace(/^https?:\/\/(www\.)?/, '').split('?')[0].replace(/\/$/, '').toLowerCase();
}

console.log('[inject_gn] Loading classified.json...');
const classified = JSON.parse(fs.readFileSync(CLASSIFIED, 'utf8'));

const byNormTitle = {};
const byNormUrl   = {};
for (const [key, info] of Object.entries(classified)) {
  const gn = extractGNFromKey(key);
  if (!gn) continue;
  byNormTitle[norm(key)] = gn;
  if (info._url) byNormUrl[normUrl(info._url)] = gn;
}
console.log('  byNormTitle:', Object.keys(byNormTitle).length, '  byNormUrl:', Object.keys(byNormUrl).length);

console.log('[inject_gn] Loading latest-24h.json...');
const data  = JSON.parse(fs.readFileSync(LATEST24H, 'utf8'));
const items = data.items || data.items_ai || [];
console.log('  items:', items.length);

// Reset all existing category/gn_label fields (so re-run is clean)
items.forEach(i => { delete i.category; delete i.gn_label; });

let byAiLabel = 0, byClassified = 0, byKeyword = 0, noMatch = 0;

for (const item of items) {
  const titleFull = [item.title, item.title_original, item.title_en].filter(Boolean).join(' ');
  const nt = norm(item.title || '');
  const no = norm(item.title_original || '');
  const nu = normUrl(item.url || '');

  let gn = null, source = '';

  // 1. ai_label direct mapping (highest priority for labeled items)
  if (!gn && item.ai_label) {
    const mapped = AI_LABEL_TO_GN[item.ai_label];
    if (mapped) { gn = mapped; source = 'ai_label'; }
  }

  // 2. classified.json exact match
  if (!gn) {
    if (byNormTitle[nt])          { gn = byNormTitle[nt];          source = 'classified-title'; }
    else if (byNormTitle[no])    { gn = byNormTitle[no];          source = 'classified-title-orig'; }
    else if (nu && byNormUrl[nu]){ gn = byNormUrl[nu];            source = 'classified-url'; }
  }

  // 3. Keyword fallback (only if title clearly robotics-related)
  if (!gn) {
    gn = keywordGN(titleFull);
    if (gn) source = 'keyword';
  }

  if (gn) {
    item.category = gn;
    item.gn_label = gn;
    if      (source === 'ai_label')      byAiLabel++;
    else if (source === 'classified-*') byClassified++;
    else                                  byKeyword++;
  } else {
    noMatch++;
  }
}

console.log(`\nResults (${items.length} items):`);
console.log(`  ai_label mapped:     ${byAiLabel}`);
console.log(`  classified matched:   ${byClassified}`);
console.log(`  keyword fallback:    ${byKeyword}`);
console.log(`  no GN match:         ${noMatch}  (这些是泛 AI 内容，不属于 GN 分类，正常)`);

fs.writeFileSync(OUTPUT, JSON.stringify(data, null, 2), 'utf8');
console.log(`\nSaved → ${OUTPUT}`);

const cats = {};
items.forEach(i => { if (i.category) cats[i.category] = (cats[i.category]||0)+1; });
console.log('\nCategory distribution:');
Object.entries(cats).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => console.log(' ', k, ':', v));
console.log('\nDone!');
