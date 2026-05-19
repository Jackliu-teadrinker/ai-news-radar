#!/usr/bin/env node
/**
 * inject_gn_min.js
 * 专门修复 latest-24h-min.json（UI实际加载的40条数据）
 */
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const MIN24H   = path.join(DATA_DIR, 'latest-24h-min.json');

const AI_LABEL_TO_GN = {
  robotics:       'GN: Physical AI',
  humanoid:       'GN: 人形机器人',
  embodied_ai:    'GN: 具身智能',
  brain_computer: 'GN: 脑机接口',
  physical_ai:    'GN: Physical AI',
};

const GN_KEYWORD_MAP = [
  { gn: 'GN: 人形机器人', kw: ['人形机器人','humanoid','双足机器人','unitree','宇树','傅利叶','智元','星动纪元','逐际','松延','Figure AI','figure ai'] },
  { gn: 'GN: 具身智能',   kw: ['具身智能','具身AI','embodied','VLA','世界模型','物理AI','physical ai','manipulation','灵巧手'] },
  { gn: 'GN: 脑机接口',   kw: ['脑机接口','brain-computer','neuralink','Neuralink','脑电','Synchron','BrainGate'] },
  { gn: 'GN: 机器人',     kw: ['robot','robots','机器人','机械臂','四足','cobot','service robot','industrial robot'] },
  { gn: 'GN: Physical AI', kw: ['physical ai'] },
];

function keywordGN(title) {
  const t = (title || '').toLowerCase();
  for (const { gn, kw } of GN_KEYWORD_MAP) {
    if (kw.some(k => t.includes(k.toLowerCase()))) return gn;
  }
  return null;
}

console.log('[inject_min] Loading latest-24h-min.json...');
const data  = JSON.parse(fs.readFileSync(MIN24H, 'utf8'));
const items = data.items || data.items_ai || [];
console.log('  items:', items.length);

let injected = 0;
for (const item of items) {
  if (item.category) continue;
  const titleFull = [item.title, item.title_original, item.title_en].filter(Boolean).join(' ');
  let gn = null;

  // 1. ai_label direct map
  if (!gn && item.ai_label) {
    gn = AI_LABEL_TO_GN[item.ai_label] || null;
  }
  // 2. Keyword fallback
  if (!gn) {
    gn = keywordGN(titleFull);
  }

  if (gn) {
    item.category = gn;
    item.gn_label = gn;
    injected++;
  }
}

console.log(`  injected: ${injected}/${items.length}`);

// 保存到 latest-24h-min.json
fs.writeFileSync(MIN24H, JSON.stringify(data, null, 2), 'utf8');
console.log(`Saved → ${MIN24H}`);

// 同时更新 latest-24h.json（确保一致性）
const MAIN = path.join(DATA_DIR, 'latest-24h.json');
if (fs.existsSync(MAIN)) {
  console.log('[inject_min] Also updating latest-24h.json...');
  const mainData = JSON.parse(fs.readFileSync(MAIN, 'utf8'));
  const mainItems = mainData.items || mainData.items_ai || [];
  let mainInjected = 0;
  for (const item of mainItems) {
    if (item.category) continue;
    const titleFull = [item.title, item.title_original, item.title_en].filter(Boolean).join(' ');
    let gn = AI_LABEL_TO_GN[item.ai_label] || keywordGN(titleFull) || null;
    if (gn) { item.category = gn; item.gn_label = gn; mainInjected++; }
  }
  fs.writeFileSync(MAIN, JSON.stringify(mainData, null, 2), 'utf8');
  console.log(`  main injected: ${mainInjected}/${mainItems.length}`);
  console.log(`Saved → ${MAIN}`);
}

// 验证
const after = JSON.parse(fs.readFileSync(MIN24H, 'utf8')).items || [];
const cats = {};
after.forEach(i => { if (i.category) cats[i.category] = (cats[i.category]||0)+1; });
console.log('\nCategory distribution (min file):');
Object.entries(cats).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => console.log(' ', k, ':', v));
console.log('\nDone!');
