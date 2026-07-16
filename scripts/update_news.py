#!/usr/bin/env python3
"""AI News Radar - RSS Aggregation Pipeline"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import html
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import feedparser
import requests

STRIP_QUERY_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'fbclid', 'gclid', 'ref', 'spm', 'mc_cid', 'mc_eid',
    '_hsenc', '_hsmi', 'mkt_tok', 'igshid',
    'gl', 'hl',
}

def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        pairs = parsed.query.split('&')
        params = []
        for pair in pairs:
            if '=' not in pair:
                continue
            k, _, v = pair.partition('=')
            if k not in STRIP_QUERY_PARAMS:
                params.append(f"{k}={v}")
        clean_query = '&'.join(params)
        reconstructed = parsed._replace(query=clean_query).geturl()
        return reconstructed.rstrip('?')
    except Exception:
        return url

def parse_opml(opml_path: str) -> list[dict]:
    tree = ET.parse(opml_path)
    root = tree.getroot()
    feeds = []
    for outline in root.iter('outline'):
        xml_url = outline.get('xmlUrl')
        if xml_url:
            feeds.append({
                'text': outline.get('text', 'unknown'),
                'xmlUrl': xml_url,
            })
    return feeds

def fetch_feed(feed: dict, timeout: int = 20) -> tuple[dict, list[dict]]:
    source_name = feed['text']
    status = {
        'feed': source_name,
        'success': False,
        'items_total': 0,
        'items_unique': 0,
        'error': None,
    }
    try:
        resp = requests.get(feed['xmlUrl'], timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; AI-News-Radar/1.0)',
        })
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        items = []
        for entry in parsed.entries:
            link = None
            if hasattr(entry, 'link'):
                link = entry.link
            elif hasattr(entry, 'id'):
                link = entry.id
            if not link:
                continue
            title = None
            if hasattr(entry, 'title'):
                title = entry.title.strip()
            if not title:
                continue
            published_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    published_at = dt.isoformat()
                except Exception:
                    pass
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                    published_at = dt.isoformat()
                except Exception:
                    pass
            site_name = None
            if hasattr(entry, 'author_detail') and hasattr(entry.author_detail, 'name'):
                site_name = entry.author_detail.name
            elif hasattr(entry, 'author'):
                site_name = entry.author
            else:
                site_name = source_name
            description = (entry.summary or entry.description or '')
            if description:
                description = html.unescape(re.sub(r'<[^>]+>', '', description)).strip()
            items.append({
                'title': title,
                'url': link,
                'published_at': published_at,
                'source': source_name,
                'site_name': site_name or source_name,
                'description': description,
            })
        status['success'] = True
        status['items_total'] = len(items)
        return status, items
    except Exception as e:
        status['error'] = str(e)[:200]
        return status, []

GN_LABEL_MAP = {
    'GN: humanoid robot':        'humanoid',
    '国外人形机器人资讯':           'humanoid',
    'GN: 人形机器人':              'humanoid',
    'GN: embodied intelligence':  'embodied_ai',
    '国外具身智能资讯':          'embodied_ai',
    'GN: 具身智能':              'embodied_ai',
    'GN: Physical AI':           'physical_ai',  # BUG#2 FIX: removed 'robot' keyword to prevent misclassification
    '国外物理AI资讯':            'physical_ai',
    'GN: 物理AI':               'physical_ai',
    'GN: BCI':                   'brain_computer',
    'GN: 脑机接口':              'brain_computer',
    '国外脑机接口资讯':          'brain_computer',
    'GN: robot':                 'robotics',
    '国外机器人资讯':               'robotics',
    'GN: 机器人':                'robotics',
}

TIER1 = ['humanoid robot','humanoid','embodied intelligence','embodied AI',
         '具身智能','人形机器人','脑机接口','brain-computer interface',
         'brain computer interface','bci']
TIER2 = ['robot','robots','robotics','robotic',
         'Tesla Optimus','Figure AI','Boston Dynamics',
         'Unitree','Fourier','宇树','傅利叶','智元','星动纪元',
         'agility robotics','1X Technologies',
         '灵巧手','机械臂','双足','协作机器人','cobot']
TIER3 = ['physical AI','dexterous manipulation','robot learning']

def relevance_score(title: str, description: str = '') -> float:
    text = (title + ' ' + description).lower()
    for kw in TIER1:
        if kw.lower() in text:
            return 0.80
    for kw in TIER2:
        if kw.lower() in text:
            return 0.65
    for kw in TIER3:
        if kw.lower() in text:
            return 0.50
    return 0.35

AUTHORITY_MAP = {'Google News': 15}

def authority_score(source: str) -> int:
    for prefix, score in AUTHORITY_MAP.items():
        if source.startswith(prefix):
            return score
    return 10

# Noise patterns with word boundaries (avoid false matches like "Interface" matching "ETF")
NOISE_PATTERNS = [
    re.compile(r'\bETF\b', re.I),
    re.compile(r'机器人ETF', re.I),
    re.compile(r'\b股票\b|\b股价\b|\b涨跌\b|\b上市\b|\bIPO\b', re.I),
    re.compile(r'扫地机器人|扫地机|扫地|roomba|robovac|roborock|dreame|ecovacs|narwal|irobot|追觅|科沃斯|云鲸|石头科技|robot vacuum|robot mop|robot cleaner|robotic vacuum|smart vacuum|auto vacuum', re.I),
    re.compile(r'概念股', re.I),
    re.compile(r'\b评级\b|\b买入\b|\b卖出\b|\b增持\b|\b目标价\b', re.I),
    re.compile(r'财报|营收|利润|亏损|盈利', re.I),
    re.compile(r'回购|分红|配股', re.I),
]

NOISE_DOMAINS = [
    'eastmoney.com','finance.sina.com.cn','stock.hexun.com',
    'stock.cnfol.com','guba.sina.com.cn','xueqiu.com',
]

MIN_DESC_LEN = 0  # Disabled: GN RSS descriptions are inherently short snippets, not full article text

def is_noise(title: str, description: str, url: str) -> tuple[bool, str]:
    text = (title + ' ' + description).lower()
    for pat in NOISE_PATTERNS:
        if pat.search(text):
            return True, pat.pattern
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        for nd in NOISE_DOMAINS:
            if domain.endswith(nd):
                return True, f'domain:{nd}'
    except Exception:
        pass
    desc_len = len(description.strip()) if description else 0
    # short_item filter: description < 200 chars = low value content
    if desc_len < MIN_DESC_LEN:
        return True, "short_item"
    return False, ''

def item_id(title: str, url: str) -> str:
    norm_title = re.sub(r'\s+', ' ', title.strip().lower())
    norm_url = normalize_url(url).lower()
    return hashlib.sha1(f"{norm_title}|{norm_url}".encode()).hexdigest()

def deduplicate(items: list[dict], seen: dict[str, str]) -> tuple[list[dict], int]:
    unique, duplicates = [], 0
    for item in items:
        sid = item_id(item['title'], item['url'])
        if sid not in seen:
            seen[sid] = sid
            unique.append(item)
        else:
            duplicates += 1
    return unique, duplicates


def normalize_title_for_dedup(title: str) -> str:
    """归一化标题用于跨 feed 去重：去标点/空格/中英括号/全半角差异
    
    Google News 会在标题末尾加 ' - Source Name' 标识发布来源，
    同一篇文章被多次抓取时这个 source 名称会变（如 'ACCESS Newswire' vs 'Yahoo Finance'），
    必须在 dedup 前剥离。
    
    FIX (2026-07-13): 旧正则把所有标点压缩成一个字符导致误合并。
    正确做法：只去掉末尾的 ' - Source' 后缀，保留标题主体中的所有字符和结构。
    """
    t = unicodedata.normalize('NFKC', title)
    # 去掉 Google News 在标题末尾加的 ' - Source Name' 后缀
    t = re.sub(r'\s+-\s+[^-–—]+$', '', t)
    # 归一化标点（去中日文标点+去西文标点），但不压缩内部字符
    t = re.sub(r'[\s　]+', ' ', t)                              # 合并空格（不删字符）
    t = re.sub(r'[，。、！？；：""''《》【】()（）]', '', t)  # 去中日文标点
    t = re.sub(r'[\-_,.!?/:;"\'\'\(\)\[\]]+', '', t)             # 去西文标点
    t = t.lower().strip()
    return t


def cross_feed_deduplicate(items: list[dict]) -> tuple[list[dict], int]:
    """跨 feed 去重（BUG#1 修复）：同一文章在不同 feed 里 id 不同但标题相同。
    
    用 normalize_title_for_dedup 作为第二去重键，保留 quality_score 最高的那条。
    返回 (unique_items, removed_count) — removed = 输入数 - 输出数。
    """
    seen_titles: dict[str, dict] = {}
    unique = []
    for item in items:
        norm = normalize_title_for_dedup(item['title'])
        if norm in seen_titles:
            existing = seen_titles[norm]
            # 比较 total_score（scored items）或 relevance（raw items），保留高的
            existing_score = existing.get('total_score', existing.get('relevance', 0))
            new_score = item.get('total_score', item.get('relevance', 0))
            if new_score > existing_score:
                # Replace: remove old from unique list, add new
                seen_titles[norm] = item
                unique = [u for u in unique if u is not existing]
                unique.append(item)
        else:
            seen_titles[norm] = item
            unique.append(item)
    removed = len(items) - len(unique)
    return unique, removed

def timeliness_score(published_at: str | None, now_ts: float) -> float:
    if not published_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        age_hours = (now_ts - dt.timestamp()) / 3600
        if age_hours < 0:
            age_hours = 0
        return max(0, 30 - age_hours)
    except Exception:
        return 0.0


def is_english(title: str) -> bool:
    """Returns True if title is predominantly English (fewer than 20% Chinese chars)."""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', title))
    total = len(title.strip())
    return total > 0 and chinese / total < 0.2

def translate_text(text: str, target: str = 'zh', _retries: int = 3) -> str:
    """Translate text using Google Translate API (free, no key required).
    
    FIX (2026-07-13): Add exponential backoff retry for 429 rate limit responses.
    Google Translate free API returns 429 when overused; without retry the whole
    batch silently returns empty strings for rate-limited requests.
    """
    if not text or not text.strip():
        return text
    url = 'https://translate.googleapis.com/translate_a/single'
    params = {
        'client': 'gtx', 'sl': 'auto', 'tl': target,
        'dt': 't', 'q': text
    }
    for attempt in range(_retries):
        try:
            r = requests.get(url, params=params, timeout=8)
            if r.status_code == 200:
                data = r.json()
                return ''.join(item[0] for item in data[0] if item[0])
            elif r.status_code == 429:
                # Rate limited — wait with exponential backoff then retry
                wait = (attempt + 1) * 1.5
                time.sleep(wait)
                continue
            else:
                return ''
        except Exception:
            if attempt == _retries - 1:
                return ''
            time.sleep(0.5)
    return ''  # all retries exhausted''

def translate_batch(texts: list[str], target: str = 'zh', max_workers: int = 2) -> dict[str, str]:
    """Translate multiple texts concurrently using Google Translate.
    Returns dict mapping original text to translated text.
    
    FIX (2026-07-13): Reduced max_workers from 8 to 2 to avoid triggering
    Google Translate free API rate limits. Combined with retry+backoff in
    translate_text(), this dramatically reduces silent translation failures.
    """
    if not texts:
        return {}
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in texts:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)

    results = {}
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _translate(text):
        return text, translate_text(text, target)

    # FIX: cap workers at 2 — Google free API rate limits fast with higher concurrency
    actual_workers = min(max_workers, 2)
    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {executor.submit(_translate, t): t for t in unique}
        for future in as_completed(futures):
            try:
                orig, trans = future.result(timeout=15)
                results[orig] = trans
            except Exception:
                orig = futures[future]
                results[orig] = orig  # fallback to original

    return results

def score_item(item: dict, now_ts: float) -> dict:
    title = item['title']
    desc = item.get('description', '')
    source = item['source']
    relevance = relevance_score(title, desc)
    authority = authority_score(source)
    depth = 5 if len(desc) >= 100 else 0
    writing_value = 5 if len(desc) >= 100 else 0
    timeliness = timeliness_score(item['published_at'], now_ts)
    total = relevance * 100 + authority + depth + writing_value + timeliness
    # BUG#2 FIX: cross-label priority
    # If title has strong robot signal (机器人/人形/具身), don't let physical_ai override
    title_lower = title.lower()
    has_robot_signal = any(kw in title_lower for kw in ['机器人', '人形', '具身智能', 'humanoid', 'embodied'])
    gn_label = GN_LABEL_MAP.get(source, 'robotics')
    if has_robot_signal and gn_label == 'physical_ai':
        gn_label = 'robotics'  # downgrade physical_ai to generic robotics
    return {
        'id': item_id(title, item['url']),
        'title': title,
        'title_zh': item.get('title_zh', ''),
        'url': item['url'],
        'published_at': item['published_at'],
        'category': source,
        'gn_label': gn_label,
        'site_name': item['site_name'],
        'source': source,
        'site_id': source,
        'description': item.get('description', ''),
        'ai_score': round(relevance * 100, 2),
        'ai_label': gn_label,
        'relevance': round(relevance, 3),
        'authority': authority,
        'depth': depth,
        'timeliness': round(timeliness, 2),
        'writing_value': writing_value,
        'total_score': round(total, 2),
    }

ARCHIVE_DAYS = 21
ANCHOR_HOUR = 19

def load_archive(path: str) -> tuple[list[dict], dict[str, str]]:
    if not os.path.exists(path):
        return [], {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        seen, valid = {}, []
        cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
        for item in data.get('items', []):
            sid = item.get('id', '') or item_id(item.get('title',''), item.get('url',''))
            seen[sid] = sid
            if item.get('published_at'):
                try:
                    dt = datetime.fromisoformat(item['published_at'].replace('Z','+00:00'))
                    if dt >= cutoff:
                        valid.append(item)
                except Exception:
                    valid.append(item)
            else:
                valid.append(item)
        return valid, seen
    except Exception:
        return [], {}

def save_archive(path: str, items: list[dict]):
    cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
    valid = []
    for item in items:
        if item.get('published_at'):
            try:
                dt = datetime.fromisoformat(item['published_at'].replace('Z','+00:00'))
                if dt >= cutoff:
                    valid.append(item)
            except Exception:
                valid.append(item)
        else:
            valid.append(item)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'generated_at': datetime.now(timezone.utc).isoformat(),
                   'total_items': len(valid), 'items': valid},
                  f, ensure_ascii=False, indent=2)

def run(output_dir: str, window_hours: int, opml_path: str, archive_days: int, window_from: str = None):
    global ARCHIVE_DAYS
    ARCHIVE_DAYS = archive_days

    feeds = parse_opml(opml_path)
    print(f"[INFO] Loaded {len(feeds)} feeds")

    all_items, seen_ids = [], {}
    now_ts = time.time()
    feed_statuses, total_dedup = [], 0
    total_noise, total_short = 0, 0

    print("[INFO] Fetching feeds...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_feed, f): f for f in feeds}
        for future in as_completed(futures):
            status, items = future.result()
            unique, n_dup = deduplicate(items, seen_ids)
            all_items.extend(unique)
            total_dedup += n_dup
            status['items_unique'] = len(unique)
            feed_statuses.append(status)
            name = futures[future]['text']
            ok = '[OK]' if status['success'] else '[FAIL]'
            d = f", -{n_dup} dup" if n_dup else ""
            print(f"  {ok} {name}: +{status['items_total']} items, {len(unique)} unique{d}")

    print(f"[INFO] Raw unique: {len(all_items)} (intra-run dedup: {total_dedup})")

    # ── Inject WeChat articles (optional) ──
    wechat_articles = []
    wechat_enabled = os.environ.get('WECHAT_COLLECTOR_ENABLED', '1').lower() in ('1', 'true', 'yes')
    if wechat_enabled:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, script_dir)
            from wechat_collector import collect_wechat_articles as _collect_wechat
            wechat_articles = _collect_wechat(
                keywords=os.environ.get('WECHAT_KEYWORDS', '').split(',') if os.environ.get('WECHAT_KEYWORDS') else None,
                hours=int(os.environ.get('WECHAT_HOURS', '24')),
                max_per_keyword=int(os.environ.get('WECHAT_MAX_PER_KW', '10')),
                include_manual=True,
            )
            print(f"[INFO] WeChat articles: {len(wechat_articles)} (WECHAT_COLLECTOR_ENABLED={wechat_enabled})")
        except Exception as e:
            print(f"[WARN] WeChat collection skipped: {e}")
            wechat_articles = []

    # BUG#1 FIX: Cross-feed deduplication
    # Items from different feeds may have different item_id but same title
    all_items, cross_dup = cross_feed_deduplicate(all_items)
    print(f"[INFO] After cross-feed dedup: {len(all_items)} (-{cross_dup} cross-feed dup)")

    # Load archive
    archive_path = os.path.join(output_dir, 'archive.json')
    archive_items, archive_seen = load_archive(archive_path)
    print(f"[INFO] Archive: {len(archive_items)} items ({ARCHIVE_DAYS}d)")

    # Step 1: Archive dedup FIRST (dedup against ALL archive items for permanent dedup)
    final_items = []
    for item in all_items:
        sid = item_id(item['title'], item['url'])
        if sid not in archive_seen:
            final_items.append(item)
    print(f"[INFO] After archive dedup: {len(final_items)} (from {len(all_items)} raw)")

    # Step 2: Noise filter (clean out low-quality items before time window)
    clean_items = []
    for item in final_items:
        noisy, reason = is_noise(item['title'], item.get('description', ''), item['url'])
        if noisy:
            total_noise += 1
            t = item['title'][:35].encode('ascii', 'replace').decode('ascii')
            print(f"  [FILTER] {reason} | {t}")
        else:
            clean_items.append(item)
    print(f"[INFO] After noise filter: {len(clean_items)} (-{total_noise} noise)")

    # Step 3: Time window only for FINAL OUTPUT (not for archive dedup)
    #
    # FIX (2026-07-14): Restore CST 19:00 anchor as default behavior.
    # Reverted from sliding window because RSS articles are concentrated during
    # daytime hours; a pure 24h sliding window misses content when run in the morning.
    # The window always starts at 19:00 CST the previous day and ends at the current time,
    # ensuring a full 24h coverage when run daily around 19:00 CST.
    shanghai = ZoneInfo('Asia/Shanghai')
    now_sh = datetime.now(shanghai)
    today_anchor = now_sh.replace(hour=ANCHOR_HOUR, minute=0, second=0, microsecond=0)
    if now_sh > today_anchor:
        start_dt = today_anchor
    else:
        start_dt = today_anchor - timedelta(days=1)
    start_ts = start_dt.timestamp()

    start_utc = datetime.fromtimestamp(start_ts, timezone.utc)
    end_utc = datetime.fromtimestamp(now_ts, timezone.utc)
    print(f"[INFO] Time window: {start_utc.strftime('%Y-%m-%d %H:%M')} UTC to {end_utc.strftime('%Y-%m-%d %H:%M')} UTC (window_hours={window_hours})")

    time_filtered = []
    missing_ts_count = 0
    bad_ts_count = 0
    for item in clean_items:
        if not item.get('published_at'):
            # FIX (2026-07-13): log missing timestamp but still include (no silent hard pass)
            missing_ts_count += 1
            if missing_ts_count <= 3:
                t = item['title'][:35].encode('ascii', 'replace').decode('ascii')
                print(f"  [WARN] missing published_at | {t}")
            time_filtered.append(item)
            continue
        try:
            dt = datetime.fromisoformat(item['published_at'].replace('Z', '+00:00'))
            if start_ts <= dt.timestamp() <= now_ts:
                time_filtered.append(item)
        except Exception:
            bad_ts_count += 1
            if bad_ts_count <= 3:
                t = item['title'][:35].encode('ascii', 'replace').decode('ascii')
                print(f"  [WARN] unparseable published_at: {item['published_at'][:30]} | {t}")
            time_filtered.append(item)
    if missing_ts_count > 3:
        print(f"  [WARN] ... and {missing_ts_count - 3} more missing published_at")
    if bad_ts_count > 3:
        print(f"  [WARN] ... and {bad_ts_count - 3} more unparseable published_at")
    print(f"[INFO] After time window: {len(time_filtered)} (from {len(clean_items)} clean, {missing_ts_count} missing_ts, {bad_ts_count} bad_ts)")
    clean_items = time_filtered

    # ── Merge WeChat articles (skip time window, already "today") ──
    if wechat_articles:
        clean_items.extend(wechat_articles)
        print(f"[INFO] Merged {len(wechat_articles)} WeChat articles → {len(clean_items)} total")

    # Sort by date desc (newest first)
    def sort_key(item):
        if not item.get('published_at'):
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(item['published_at'].replace('Z','+00:00'))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    clean_items.sort(key=sort_key, reverse=True)
    print(f"[INFO] Sorted by date (newest first)")

    # Score
    # Pre-translate English titles
    english_titles = [item['title'] for item in clean_items if is_english(item['title'])]
    if english_titles:
        print(f"[INFO] Translating {len(english_titles)} English titles...")
        trans_map = translate_batch(english_titles)
        for item in clean_items:
            if item['title'] in trans_map:
                item['title_zh'] = trans_map[item['title']]

    scored = [score_item(item, now_ts) for item in clean_items]
    scored.sort(key=lambda x: x['total_score'], reverse=True)
    print(f"[INFO] Scored: {len(scored)}")

    generated_at = datetime.now(timezone.utc).isoformat()
    os.makedirs(output_dir, exist_ok=True)

    # latest-24h-min.json: top 500
    min_out = {'generated_at': generated_at, 'total_items': len(scored[:500]), 'items': scored[:500]}
    with open(os.path.join(output_dir, 'latest-24h-min.json'), 'w', encoding='utf-8') as f:
        json.dump(min_out, f, ensure_ascii=False, indent=2)
    print(f"[INFO] latest-24h-min.json: {len(scored[:500])} items")

    # latest-24h-all.json: all scored
    all_out = {'generated_at': generated_at, 'total_items': len(scored), 'items': scored}
    with open(os.path.join(output_dir, 'latest-24h-all.json'), 'w', encoding='utf-8') as f:
        json.dump(all_out, f, ensure_ascii=False, indent=2)
    print(f"[INFO] latest-24h-all.json: {len(scored)} items")

    # Update archive
    updated = archive_items + scored
    save_archive(archive_path, updated)
    print(f"[INFO] Archive updated: {len(updated)} total")

    # source-status.json
    status_out = {
        'generated_at': generated_at,
        'feeds': feed_statuses,
        'summary': {
            'total_feeds': len(feeds),
            'successful_feeds': sum(1 for s in feed_statuses if s['success']),
            'failed_feeds': sum(1 for s in feed_statuses if not s['success']),
            'total_items': len(all_items),
            'deduplicated': total_dedup,
            'noise_filtered': total_noise,
            'short_filtered': total_short,
        }
    }
    with open(os.path.join(output_dir, 'source-status.json'), 'w', encoding='utf-8') as f:
        json.dump(status_out, f, ensure_ascii=False, indent=2)
    ok_feeds = status_out['summary']['successful_feeds']
    print(f"[INFO] source-status.json: {ok_feeds}/{len(feeds)} feeds OK")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', default='data')
    p.add_argument('--window-hours', type=int, default=24)
    p.add_argument('--rss-opml', default='feeds/follow.example.opml')
    p.add_argument('--window-from', type=str, default=None,
                        help='Start of time window (YYYY-MM-DD, defaults to yesterday 9AM CST)')
    p.add_argument('--archive-days', type=int, default=21)
    args = p.parse_args()
    run(args.output_dir, args.window_hours, args.rss_opml, args.archive_days, args.window_from)
