#!/usr/bin/env python3
"""
AI News Radar - RSS Aggregation Pipeline
Refactored from LearnPrompt/ai-news-radar architecture
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import feedparser
import requests

# ── URL normalization ────────────────────────────────────────────────────────

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

# ── OPML parsing ─────────────────────────────────────────────────────────────

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

# ── RSS fetching ─────────────────────────────────────────────────────────────

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

            description = ''
            if hasattr(entry, 'summary'):
                description = entry.summary
            elif hasattr(entry, 'description'):
                description = entry.description

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

# ── GN classification ────────────────────────────────────────────────────────

GN_LABEL_MAP = {
    'GN: 人形机器人':    'humanoid',
    'GN: 人形机器人-ZH': 'humanoid',
    'GN: 具身智能':      'embodied_ai',
    'GN: 具身智能-ZH':   'embodied_ai',
    'GN: Physical AI':  'physical_ai',
    'GN: 脑机接口':      'brain_computer',
    'GN: 脑机接口-ZH':   'brain_computer',
    'GN: robot':        'robotics',
    'GN: 机器人-ZH':     'robotics',
}

# ── Relevance scoring ────────────────────────────────────────────────────────

RELEVANCE_KEYWORDS = [
    'humanoid', 'robot', 'robots', 'robotics', 'embodied', 'embodied AI',
    'embodied intelligence', 'bci', 'brain-computer', 'brain computer',
    '具身', '具身智能', '人形机器人', '脑机接口', '机械臂',
    '灵巧手', '双足', '宇树', '傅利叶', '智元', '星动纪元',
    'Figure AI', 'Tesla Optimus', 'Boston Dynamics',
    'agility robotics', '1X Technologies', 'Unitree', 'Fourier',
    '机械手', '四足', '轮式', '协作机器人', 'cobot',
]

def relevance_score(title: str, description: str) -> float:
    text = (title + ' ' + description).lower()
    for kw in RELEVANCE_KEYWORDS:
        if kw.lower() in text:
            if kw.lower() in ['humanoid', '具身', '人形机器人', '脑机接口']:
                return 0.80
            return 0.65
    return 0.35

AUTHORITY_MAP = {'Google News': 15}

def authority_score(source: str) -> int:
    for prefix, score in AUTHORITY_MAP.items():
        if source.startswith(prefix):
            return score
    return 10

# ── ID generation ────────────────────────────────────────────────────────────

def item_id(title: str, url: str) -> str:
    norm_title = re.sub(r'\s+', ' ', title.strip().lower())
    norm_url = normalize_url(url).lower()
    return hashlib.sha1(f"{norm_title}|{norm_url}".encode()).hexdigest()

# ── Deduplication ────────────────────────────────────────────────────────────

def deduplicate(items: list[dict], seen: set[str]) -> tuple[list[dict], int]:
    unique, duplicates = [], 0
    for item in items:
        sid = item_id(item['title'], item['url'])
        if sid not in seen:
            seen.add(sid)
            unique.append(item)
        else:
            duplicates += 1
    return unique, duplicates

# ── Timeliness scoring ──────────────────────────────────────────────────────

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

# ── Scoring ─────────────────────────────────────────────────────────────────

def score_item(item: dict, now_ts: float) -> dict:
    title = item['title']
    desc = item.get('description', '')
    source = item['source']

    relevance = relevance_score(title, desc)
    authority = authority_score(source)
    depth = 5 if desc else 0
    writing_value = 5 if desc else 0
    timeliness = timeliness_score(item['published_at'], now_ts)
    total = relevance * 100 + authority + depth + writing_value + timeliness

    gn_label = GN_LABEL_MAP.get(source, 'robotics')

    return {
        'id': item_id(title, item['url']),
        'title': title,
        'url': item['url'],
        'published_at': item['published_at'],
        'category': source,
        'gn_label': gn_label,
        'site_name': item['site_name'],
        'source': source,
        'site_id': source,
        'ai_score': round(relevance * 100, 2),
        'ai_label': gn_label,
        'relevance': round(relevance, 3),
        'authority': authority,
        'depth': depth,
        'timeliness': round(timeliness, 2),
        'writing_value': writing_value,
        'total_score': round(total, 2),
    }

# ── Archive management ─────────────────────────────────────────────────────

ARCHIVE_DAYS = 21

def load_archive(archive_path: str) -> tuple[list[dict], dict[str, str]]:
    if not os.path.exists(archive_path):
        return [], {}
    try:
        with open(archive_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        seen_ids = {}
        valid_items = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
        for item in data.get('items', []):
            sid = item.get('id', '')
            seen_ids[sid] = sid
            if item.get('published_at'):
                try:
                    dt = datetime.fromisoformat(item['published_at'].replace('Z', '+00:00'))
                    if dt >= cutoff:
                        valid_items.append(item)
                except Exception:
                    valid_items.append(item)
            else:
                valid_items.append(item)
        return valid_items, seen_ids
    except Exception:
        return [], {}

def save_archive(archive_path: str, items: list[dict]):
    cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
    valid = []
    for item in items:
        if item.get('published_at'):
            try:
                dt = datetime.fromisoformat(item['published_at'].replace('Z', '+00:00'))
                if dt >= cutoff:
                    valid.append(item)
            except Exception:
                valid.append(item)
        else:
            valid.append(item)
    data = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'total_items': len(valid),
        'items': valid,
    }
    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Main pipeline ────────────────────────────────────────────────────────────

def run(output_dir: str, window_hours: int, opml_path: str, archive_days: int):
    global ARCHIVE_DAYS
    ARCHIVE_DAYS = archive_days

    feeds = parse_opml(opml_path)
    print(f"[INFO] Loaded {len(feeds)} feeds from OPML")

    all_items = []
    seen_ids_global: set[str] = set()
    now_ts = time.time()
    feed_statuses = []
    total_dedup = 0

    print("[INFO] Fetching feeds...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_feed, f): f for f in feeds}
        for future in as_completed(futures):
            status, items = future.result()
            unique, n_dup = deduplicate(items, seen_ids_global)
            all_items.extend(unique)
            total_dedup += n_dup
            status['items_unique'] = len(unique)
            feed_statuses.append(status)
            feed_name = futures[future]['text']
            ok = '[OK]' if status['success'] else '[FAIL]'
            dup_str = f", -{n_dup} duplicates" if n_dup else ""
            print(f"  {ok} {feed_name}: +{status['items_total']} items, {len(unique)} unique{dup_str}")

    print(f"[INFO] Total: {len(all_items)} unique (after {total_dedup} intra-run dedup)")

    # Load existing archive
    archive_path = os.path.join(output_dir, 'archive.json')
    archive_items, archive_seen = load_archive(archive_path)
    print(f"[INFO] Archive: {len(archive_items)} items (last {ARCHIVE_DAYS} days)")

    # Global dedup against archive
    final_items = []
    for item in all_items:
        sid = item_id(item['title'], item['url'])
        if sid not in archive_seen:
            final_items.append(item)

    scored = [score_item(item, now_ts) for item in final_items]
    scored.sort(key=lambda x: x['total_score'], reverse=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    os.makedirs(output_dir, exist_ok=True)

    # latest-24h-min.json: top 500
    min_output = {
        'generated_at': generated_at,
        'total_items': len(scored[:500]),
        'items': scored[:500],
    }
    with open(os.path.join(output_dir, 'latest-24h-min.json'), 'w', encoding='utf-8') as f:
        json.dump(min_output, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Wrote {len(scored[:500])} items to latest-24h-min.json")

    # latest-24h-all.json: all items this run
    all_output = {
        'generated_at': generated_at,
        'total_items': len(scored),
        'items': scored,
    }
    with open(os.path.join(output_dir, 'latest-24h-all.json'), 'w', encoding='utf-8') as f:
        json.dump(all_output, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Wrote {len(scored)} items to latest-24h-all.json")

    # Update archive
    updated_archive = archive_items + scored
    save_archive(archive_path, updated_archive)
    print(f"[INFO] Updated archive: {len(updated_archive)} total items")

    # source-status.json
    status_output = {
        'generated_at': generated_at,
        'feeds': feed_statuses,
        'summary': {
            'total_feeds': len(feeds),
            'successful_feeds': sum(1 for s in feed_statuses if s['success']),
            'failed_feeds': sum(1 for s in feed_statuses if not s['success']),
            'total_items': len(all_items),
            'deduplicated': total_dedup,
        }
    }
    with open(os.path.join(output_dir, 'source-status.json'), 'w', encoding='utf-8') as f:
        json.dump(status_output, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Wrote source-status.json ({status_output['summary']['successful_feeds']}/{len(feeds)} feeds OK)")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AI News Radar - RSS Aggregator')
    parser.add_argument('--output-dir', default='data', help='Output directory')
    parser.add_argument('--window-hours', type=int, default=24, help='Time window in hours')
    parser.add_argument('--rss-opml', default='feeds/follow.example.opml', help='OPML file path')
    parser.add_argument('--archive-days', type=int, default=21, help='Archive retention days')
    args = parser.parse_args()

    run(args.output_dir, args.window_hours, args.rss_opml, args.archive_days)
