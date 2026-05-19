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
from datetime import datetime, timezone
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
    """Remove tracking params from URL."""
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
        # Remove trailing '?' if no params left
        return reconstructed.rstrip('?')
    except Exception:
        return url

# ── OPML parsing ─────────────────────────────────────────────────────────────

def parse_opml(opml_path: str) -> list[dict]:
    """Parse OPML and return list of {text, xmlUrl} dicts."""
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

def fetch_feed(feed: dict, timeout: int = 20) -> list[dict]:
    """Fetch a single RSS feed and return list of items."""
    items = []
    source_name = feed['text']
    try:
        resp = requests.get(feed['xmlUrl'], timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; AI-News-Radar/1.0)',
        })
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        for entry in parsed.entries:
            # Extract URL
            link = None
            if hasattr(entry, 'link'):
                link = entry.link
            elif hasattr(entry, 'id'):
                link = entry.id
            if not link:
                continue

            # Extract title
            title = None
            if hasattr(entry, 'title'):
                title = entry.title.strip()
            if not title:
                continue

            # Extract published time
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

            # Extract site_name
            site_name = getattr(entry, 'author_detail', None)
            if site_name and hasattr(site_name, 'name'):
                site_name = site_name.name
            elif hasattr(entry, 'author'):
                site_name = entry.author
            else:
                site_name = source_name

            # Extract description for depth scoring
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
    except Exception as e:
        print(f"  [WARN] Failed to fetch {source_name}: {e}", file=sys.stderr)
    return items

# ── GN classification ───────────────────────────────────────────────────────

GN_LABEL_MAP = {
    'GN: 人形机器人':       'humanoid',
    'GN: 人形机器人-ZH':    'humanoid',
    'GN: 具身智能':         'embodied_ai',
    'GN: 具身智能-ZH':      'embodied_ai',
    'GN: Physical AI':     'physical_ai',
    'GN: 脑机接口':         'brain_computer',
    'GN: 脑机接口-ZH':      'brain_computer',
    'GN: 机器人学习':       'robotics',
    'arXiv Robotics':      'robotics',
    'arXiv Embodied AI':   'embodied_ai',
    'TechCrunch Robotics': 'robotics',
    '36kr':                'robotics',
}

# ── Relevance scoring ────────────────────────────────────────────────────────

RELEVANCE_KEYWORDS = [
    'humanoid', 'robot', 'robots', 'robotics', 'embodied', 'embodied AI',
    'embodied intelligence', 'bci', 'brain-computer', 'brain computer',
    '具身', '具身智能', '人形机器人', '脑机接口', '机械臂',
    '灵巧手', '双足', '宇树', '傅利叶', '智元', '星动纪元',
    'Figure AI', 'Tesla Optimus', 'Boston Dynamics',
    'agility robotics', '1X Technologies', 'Unitree', ' Fourier',
]

def relevance_score(title: str, description: str, source: str) -> float:
    """Return base relevance score 0-1."""
    text = (title + ' ' + description).lower()
    # Exact keyword match gives higher score
    for kw in RELEVANCE_KEYWORDS:
        if kw.lower() in text:
            if kw.lower() in ['humanoid', '具身', '人形机器人', '脑机接口']:
                return 0.80
            return 0.65
    return 0.35

AUTHORITY_MAP = {
    'Google News': 15,
}

def authority_score(source: str) -> int:
    for prefix, score in AUTHORITY_MAP.items():
        if source.startswith(prefix):
            return score
    return 10

# ── ID generation ────────────────────────────────────────────────────────────

def item_id(title: str, url: str) -> str:
    """SHA1 of normalized title + URL."""
    norm_title = re.sub(r'\s+', ' ', title.strip().lower())
    norm_url = normalize_url(url).lower()
    return hashlib.sha1(f"{norm_title}|{norm_url}".encode()).hexdigest()

# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(items: list[dict], seen: set[str]) -> list[dict]:
    """Filter out already-seen IDs, add new ones to seen."""
    unique = []
    for item in items:
        sid = item_id(item['title'], item['url'])
        if sid not in seen:
            seen.add(sid)
            unique.append(item)
    return unique

# ── Timeliness scoring ───────────────────────────────────────────────────────

def timeliness_score(published_at: str | None, now_ts: float) -> float:
    """Hours ago → score 30→0, linear decay over 24h."""
    if not published_at:
        return 0.0
    try:
        # Parse ISO format
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        age_hours = (now_ts - dt.timestamp()) / 3600
        if age_hours < 0:
            age_hours = 0
        return max(0, 30 - age_hours)
    except Exception:
        return 0.0

# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(output_dir: str, window_hours: int, opml_path: str):
    feeds = parse_opml(opml_path)
    print(f"[INFO] Loaded {len(feeds)} feeds from OPML")

    all_items = []
    seen_ids: set[str] = set()
    now_ts = time.time()

    # Concurrent fetch
    print("[INFO] Fetching feeds...")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_feed, f): f for f in feeds}
        for future in as_completed(futures):
            items = future.result()
            unique = deduplicate(items, seen_ids)
            all_items.extend(unique)
            print(f"  {futures[future]['text']}: +{len(items)} items, {len(unique)} unique")

    # Filter by time window
    cutoff = now_ts - (window_hours * 3600)
    filtered = []
    for item in all_items:
        if not item['published_at']:
            # No timestamp → include (unknown age)
            filtered.append(item)
            continue
        try:
            dt = datetime.fromisoformat(item['published_at'].replace('Z', '+00:00'))
            if dt.timestamp() >= cutoff:
                filtered.append(item)
        except Exception:
            filtered.append(item)

    # Score each item
    scored = []
    for item in filtered:
        title = item['title']
        desc = item.get('description', '')
        source = item['source']

        relevance = relevance_score(title, desc, source)
        authority = authority_score(source)
        depth = 5 if desc else 0
        writing_value = 5 if desc else 0
        timeliness = timeliness_score(item['published_at'], now_ts)

        total = relevance * 100 + authority + depth + writing_value + timeliness

        gn_label = GN_LABEL_MAP.get(source, 'robotics')

        scored.append({
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
        })

    # Sort by total_score descending, cap at 500
    scored.sort(key=lambda x: x['total_score'], reverse=True)
    scored = scored[:500]

    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'total_items': len(scored),
        'items': scored,
    }

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, 'latest-24h-min.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] Wrote {len(scored)} items to {out_path}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AI News Radar - RSS Aggregator')
    parser.add_argument('--output-dir', default='data', help='Output directory')
    parser.add_argument('--window-hours', type=int, default=24, help='Time window in hours')
    parser.add_argument('--rss-opml', default='feeds/follow.example.opml', help='OPML file path')
    args = parser.parse_args()

    run(args.output_dir, args.window_hours, args.rss_opml)
