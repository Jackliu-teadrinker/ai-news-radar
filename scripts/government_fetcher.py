#!/usr/bin/env python3
"""政府专区抓取器 — 中国机器人与具身智能政策新闻

按 ANCHOR_HOUR=19 CST 规则抓取政策新闻，输出到 data/government-news.json。

时间窗口：
- 早 19:00 CST 跑：昨天 19:00 → 现在（最多19h）
- 晚 19:00 CST 跑：今天 19:00 → 现在（最多24h）

设计原则：
1. 政策新闻比科技新闻更重"时效"，轻"深度"——只保留最近窗口内的
2. 用 Google News RSS 代理，因为中国政府网站大多无 RSS
3. 与锚点专区共享同一套抓取基础设施（parse_opml / fetch_anchor_site）
4. 独立于 main feed：政策新闻不进入主数据，只输出到 government-news.json
"""
import os
import re
import sys
import json
import time
import html
import urllib3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import feedparser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 配置 ──
ANCHOR_HOUR = 19
GOV_MIN_SCORE = 45          # 相关度阈值（政策新闻更新慢，放宽以覆盖历史重要政策）
GOV_MAX_ITEMS = 30          # 最多展示条数
WINDOW_HOURS = 24           # 默认滑动窗口（兜底，实际被 anchor 规则覆盖）
CUSTOM_OPML = os.path.join(os.path.dirname(__file__), '..', 'feeds', 'government.opml')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# 政策关键词（标题/摘要包含则提高权重）
POLICY_KEYWORDS = [
    '政策', '规划', '通知', '意见', '实施方案', '行动计划',
    '指导意见', '专项', '部署', '印发', '发布', '申报',
    '人形机器人', '具身智能', '机器人', '人工智能',
]


def parse_opml(path: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    if not os.path.exists(path):
        return []
    tree = ET.parse(path)
    feeds = []
    for outline in tree.iter('outline'):
        url = outline.get('xmlUrl') or outline.get('url')
        if not url:
            continue
        feeds.append({
            'text': outline.get('text', ''),
            'xmlUrl': url,
            'url': url,
            'type': outline.get('type', 'rss'),
        })
    return feeds


def fetch_gov_feed(feed: dict, timeout: int = 30, max_items: int = 30) -> tuple[dict, list[dict]]:
    """Fetch a government news feed. Try RSS first, fallback to HTML scrape."""
    source_name = feed['text']
    url = feed.get('xmlUrl', feed.get('url', ''))
    feed_type = feed.get('type', 'rss')
    status = {'feed': source_name, 'success': False, 'items_total': 0}

    if feed_type != 'rss':
        return status, []

    try:
        resp = requests.get(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; AI-News-Radar/1.0)'},
            timeout=timeout, allow_redirects=True, verify=False
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        items = []
        for entry in parsed.entries[:max_items]:
            link = entry.get('link') or entry.get('id')
            if not link:
                continue
            title = entry.get('title', '').strip()
            if not title:
                continue
            published_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    published_at = dt.isoformat()
                except Exception:
                    pass
            description = (entry.get('summary') or entry.get('description') or '')
            if description:
                description = html.unescape(re.sub(r'<[^>]+>', '', description)).strip()
            items.append({
                'title': title,
                'url': link,
                'published_at': published_at,
                'source': source_name,
                'site_name': source_name,
                'description': description[:300],
            })
        status['success'] = True
        status['items_total'] = len(items)
        return status, items
    except Exception as e:
        status['error'] = str(e)[:80]
        print(f"  [FAIL] {source_name}: {status['error']}")
        return status, []


def policy_relevance_score(title: str, desc: str, source: str = '') -> float:
    """Score how policy-relevant an item is (0-1)."""
    text = (title + ' ' + desc).lower()
    source_lower = source.lower()
    
    # Start with base score for domain keywords
    score = 0.0
    
    # Domain keywords (robotics/embodied AI) - essential for relevance
    domain_matched = False
    for kw in ['人形机器人', '具身智能', '机器人', '人工智能', '智能机器人', '工业机器', '服务机器人', '无人', '自动驾驶']:
        if kw in text:
            score += 0.12
            domain_matched = True
    
    # If no domain match, not relevant
    if not domain_matched:
        return 0.0
    
    # Policy keywords - boost score
    for kw in ['政策', '规划', '通知', '意见', '实施方案', '行动计划', '指导意见', '专项', '印发', '发布', '申报', '部署', '提出', '要求', '推动', '发展', '意见', '决定', '条例', '办法']:
        if kw in text:
            score += 0.10
    
    # Source authority - gov.cn sources get high bonus
    if 'gov.cn' in source_lower or 'miit.gov.cn' in source_lower or 'ncsti.gov.cn' in source_lower or 'sasac.gov.cn' in source_lower:
        score += 0.30
    elif '新华社' in source or '新华网' in source:
        score += 0.25
    elif '日报' in source or '报' in source:
        score += 0.20
    
    return min(score, 1.0)


def score_item(item: dict, now_ts: float) -> dict:
    """Score a government news item."""
    title = item['title']
    desc = item.get('description', '')
    source = item['source']
    relevance = policy_relevance_score(title, desc, source)
    # Authority: gov.cn > 新华社 > 其他
    if 'gov.cn' in source:
        authority = 10
    elif '新华社' in source or '新华网' in source:
        authority = 8
    elif any(s in source for s in ['ncsti', 'miit', '教育部', '科技部']):
        authority = 7
    else:
        authority = 5
    # Depth: longer description = more depth
    depth = 5 if len(desc) >= 100 else 0
    writing_value = 3 if len(desc) >= 80 else 0
    # Timeliness: same formula as update_news.py
    try:
        pub_dt = datetime.fromisoformat(item['published_at'].replace('Z', '+00:00'))
        age_hours = (now_ts - pub_dt.timestamp()) / 3600
        timeliness = max(0, 10 - age_hours / 6)  # 6h = full score, 60h = 0
    except Exception:
        timeliness = 0
    total = relevance * 100 + authority + depth + writing_value + timeliness
    return {
        'id': f"gov-{abs(hash(item['url'])) % 0xFFFFFFFF:08x}",
        'title': title,
        'url': item['url'],
        'published_at': item['published_at'],
        'source': source,
        'site_name': source,
        'description': desc[:300],
        'ai_score': round(relevance * 100, 2),
        'relevance': round(relevance, 3),
        'authority': authority,
        'depth': depth,
        'timeliness': round(timeliness, 2),
        'writing_value': writing_value,
        'total_score': round(total, 2),
    }


def main():
    CST = timezone(timedelta(hours=8))
    now_sh = datetime.now(CST)
    today_anchor = now_sh.replace(hour=ANCHOR_HOUR, minute=0, second=0, microsecond=0)
    if now_sh < today_anchor:
        start_dt = today_anchor - timedelta(days=1)
    else:
        start_dt = today_anchor
    start_ts = start_dt.timestamp()
    now_ts = time.time()

    print(f"[GOV] Window (CST): {start_dt.strftime('%Y-%m-%d %H:%M')} → {now_sh.strftime('%Y-%m-%d %H:%M')}")
    print(f"[GOV] Window hours: {(now_sh - start_dt).total_seconds() / 3600:.1f}h")

    # Load feeds
    opml_path = os.path.join(OUTPUT_DIR, '..', 'feeds', 'government.opml')
    if not os.path.exists(opml_path):
        opml_path = CUSTOM_OPML
    feeds = parse_opml(opml_path)
    print(f"[GOV] Loaded {len(feeds)} feeds from government.opml")

    # Fetch all
    all_items = []
    seen_ids = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_gov_feed, f): f for f in feeds}
        for future in as_completed(futures):
            status, items = future.result()
            for it in items:
                sid = it['url']
                if sid in seen_ids:
                    continue
                seen_ids[sid] = sid
                all_items.append(it)
            print(f"  {status['feed']}: {status['items_total']} raw")
    print(f"[GOV] Total unique: {len(all_items)}")

    # Time window filter
    in_window = []
    for it in all_items:
        if not it.get('published_at'):
            in_window.append(it)
            continue
        try:
            dt = datetime.fromisoformat(it['published_at'].replace('Z', '+00:00'))
            if start_ts <= dt.timestamp() <= now_ts:
                in_window.append(it)
        except Exception:
            in_window.append(it)
    print(f"[GOV] In anchor window: {len(in_window)}")

    # Score + filter
    scored = [score_item(it, now_ts) for it in in_window]
    high = [it for it in scored if it.get('ai_score', 0) >= GOV_MIN_SCORE]
    print(f"[GOV] After relevance >= {GOV_MIN_SCORE}: {len(high)}/{len(scored)}")

    # Fallback: expand to 7d if < 5 items (policy news is infrequent)
    fallback_used = False
    if len(high) < 5:
        fb_window = 336  # 14d（政策新闻发布频率低，需展示历史积累）
        print(f"[GOV] Too few items ({len(high)}), expanding to {fb_window}h fallback...")
        fb_start = now_sh - timedelta(hours=fb_window)
        fb_start_ts = fb_start.timestamp()
        fb_items = []
        for it in all_items:
            if not it.get('published_at'):
                fb_items.append(it)
                continue
            try:
                dt = datetime.fromisoformat(it['published_at'].replace('Z', '+00:00'))
                if fb_start_ts <= dt.timestamp() <= now_ts:
                    fb_items.append(it)
            except Exception:
                fb_items.append(it)
        scored_fb = [score_item(it, now_ts) for it in fb_items]
        high = [it for it in scored_fb if it.get('ai_score', 0) >= GOV_MIN_SCORE]
        fallback_used = True
        print(f"[GOV] Fallback result: {len(high)} items (window={fb_window}h)")

    # Sort by published date (newest first), limit
    high.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    high = high[:GOV_MAX_ITEMS]

    # Build output
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'window_start': start_dt.isoformat(),
        'window_end': now_sh.isoformat(),
        'total_items': len(high),
        'fallback_used': fallback_used,
        'items': high,
    }
    out_path = os.path.join(OUTPUT_DIR, 'government-news.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[GOV] Wrote {out_path}: {len(high)} items")

    # Summary
    for i, it in enumerate(high[:10], 1):
        pub = it.get('published_at', '?')[:19]
        print(f"  {i:2d}. [{pub}] {it['source'][:25]:<25} | {it['title'][:55]}")


if __name__ == '__main__':
    main()
