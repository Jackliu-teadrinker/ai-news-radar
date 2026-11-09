"""
独立锚点刷新脚本 — 只跑 custom-anchors.json 的逻辑，不动主数据
按 ANCHOR_HOUR=19 锚点规则（昨天 19:00 CST → 现在）取数
"""
import os
import sys
import json
import time
import re
import html
import urllib3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import feedparser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ANCHOR_HOUR = 19
ANCHOR_MIN_SCORE = 70
FALLBACK_HOURS = 168  # 7天（仅当窗口内 0 条时启用）
WORKSPACE = r"C:\Users\86571\.openclaw\workspace\ai-news-radar"
CUSTOM_OPML = os.path.join(WORKSPACE, "feeds", "custom.opml")
OUTPUT_DIR = os.path.join(WORKSPACE, "data")


def parse_opml(path):
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


def fetch_anchor_site(feed, timeout=30, max_items=30):
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


# ── 复用 update_news.py 的相关度/权威/时效评分 ──
sys.path.insert(0, os.path.join(WORKSPACE, 'scripts'))
try:
    from update_news import relevance_score, authority_score, timeliness_score, item_id, score_item
except Exception as e:
    print(f"[FATAL] 无法导入 update_news 评分函数: {e}")
    sys.exit(1)


def main():
    CST = timezone(timedelta(hours=8))
    now_local = datetime.now(CST)
    today_anchor = now_local.replace(hour=ANCHOR_HOUR, minute=0, second=0, microsecond=0)
    if now_local < today_anchor:
        window_start = today_anchor - timedelta(days=1)
    else:
        window_start = today_anchor
    window_end = now_local
    start_ts = window_start.timestamp()
    now_ts = time.time()

    print(f"[INFO] Window (CST): {window_start.isoformat()} → {window_end.isoformat()}")
    print(f"[INFO] Window hours: {(window_end-window_start).total_seconds()/3600:.1f}h")

    feeds = parse_opml(CUSTOM_OPML)
    print(f"[INFO] Loaded {len(feeds)} custom feeds")

    all_items = []
    seen = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_anchor_site, f): f for f in feeds}
        for future in as_completed(futures):
            status, items = future.result()
            for it in items:
                sid = item_id(it['title'], it['url'])
                if sid in seen:
                    continue
                seen[sid] = sid
                all_items.append(it)
            print(f"  {status['feed']}: {status['items_total']} raw → {len([i for i in items if item_id(i['title'],i['url']) in seen])} unique")
    print(f"[INFO] Total unique: {len(all_items)}")

    # 时间窗口过滤
    in_window = []
    no_ts = []
    future = []
    for it in all_items:
        if not it.get('published_at'):
            no_ts.append(it)
            continue
        try:
            dt = datetime.fromisoformat(it['published_at'].replace('Z','+00:00'))
        except Exception:
            no_ts.append(it)
            continue
        if dt.timestamp() > now_ts:
            future.append(it)
            continue
        if dt.timestamp() >= start_ts:
            in_window.append(it)
    print(f"[INFO] In 19h window: {len(in_window)} | no_ts: {len(no_ts)} | future: {len(future)}")

    # 评分 + ≥70 过滤
    now_ts_safe = time.time()
    scored = [score_item(it, now_ts_safe) for it in in_window]
    high = [it for it in scored if it.get('ai_score', 0) >= ANCHOR_MIN_SCORE]
    print(f"[INFO] After ai_score >= {ANCHOR_MIN_SCORE}: {len(high)}/{len(scored)}")

    # Fallback：仅在窗口内 0 条且 7 天内有数据时启用（防止空白板块）
    final_items = high
    if len(high) == 0:
        print(f"[INFO] Empty in 19h window, trying {FALLBACK_HOURS}h (7d) fallback...")
        fb_start = now_local - timedelta(hours=FALLBACK_HOURS)
        fb_start_ts = fb_start.timestamp()
        in_fb = []
        for it in all_items:
            if not it.get('published_at'):
                continue
            try:
                dt = datetime.fromisoformat(it['published_at'].replace('Z','+00:00'))
            except Exception:
                continue
            if fb_start_ts <= dt.timestamp() <= now_ts:
                in_fb.append(it)
        scored_fb = [score_item(it, now_ts_safe) for it in in_fb]
        high_fb = [it for it in scored_fb if it.get('ai_score', 0) >= ANCHOR_MIN_SCORE]
        # 只取 ≥ 当前窗口结束时间 - 7天 的所有，按发布时间倒序
        high_fb.sort(key=lambda x: x.get('published_at',''), reverse=True)
        final_items = high_fb[:30]  # 最多 30 条
        print(f"[INFO] Fallback result: {len(final_items)} items (7d window)")

    # 按发布时间倒序
    final_items.sort(key=lambda x: x.get('published_at',''), reverse=True)

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'total_items': len(final_items),
        'items': final_items,
        'fallback_used': len(high) == 0 and len(final_items) > 0,
    }
    out_path = os.path.join(OUTPUT_DIR, 'custom-anchors.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] Wrote {out_path}: {len(final_items)} items, fallback={out['fallback_used']}")


if __name__ == '__main__':
    main()