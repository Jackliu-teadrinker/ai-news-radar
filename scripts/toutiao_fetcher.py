#!/usr/bin/env python3
"""今日头条专区抓取器 — 抓取 toutiao.com / 头条号上的机器人资讯

通过 Google News RSS 搜索，使用多关键词策略 + 严格相关度过滤。
主雷达精选锚点已覆盖 量子位/36kr/雷锋网 等信源，本专区专注头条号内容。
输出到 data/toutiao-news.json。
"""
import os
import re
import sys
import json
import urllib.parse
import urllib3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 核心领域关键词 — 必须至少匹配一个
DOMAIN_KEYWORDS = [
    '人形机器人', '具身智能', '物理AI', '脑机接口',
    'Embodied AI', 'humanoid', 'embodied intelligence', 'physical AI', 'BCI',
    '宇树', '智元', '傅利叶', '优必选', '银河通用', '星动纪元',
]

# 排除关键词 — 出现就过滤
EXCLUDE_KEYWORDS = [
    '父亲', '母亲', '家庭', '情感', '国学', '非遗', '搏击', '泰拳', '功夫',
    '娱乐', '明星', '网红', '直播', '粉丝', '考研', '国画', '南美洲',
    '旅游', '游戏', '音乐', '完赛', '世界杯', '英语名字', '英文名字',
    '兴趣认证', '黄昏', '新一年', '全力', '今日', '头条',  # 通用干扰
]

# 主雷达已有信源 — 不重复收录
ANCHOR_DOMAINS = [
    'qbitai.com', 'jiqizhixin.com', '36kr.com', 'leiphone.com',
    'techcrunch.com', 'wired.com', 'venturebeat.com', 'ieee.org',
    'techxplore.com', 'huggingface.co',
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'toutiao-news.json')


def is_relevant(title: str, desc: str = '', source: str = '') -> bool:
    """判断是否相关：必须命中领域关键词 + 不在主雷达信源 + 不含排除词。"""
    text = title + ' ' + desc

    # 排除无关内容
    if any(ex in text for ex in EXCLUDE_KEYWORDS):
        return False

    # 必须命中领域关键词
    if not any(kw in text for kw in DOMAIN_KEYWORDS):
        return False

    # 排除主雷达已有的信源
    if any(domain in source.lower() for domain in ANCHOR_DOMAINS):
        return False

    return True


def search_toutiao(keyword: str, max_results: int = 30) -> list[dict]:
    """通过 Google News RSS 搜索今日头条相关条目。"""
    # 不限定域名，通过关键词过滤
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            print(f"  [FAIL] {keyword}: HTTP {resp.status_code}")
            return []

        import feedparser
        parsed = feedparser.parse(resp.text)

        items = []
        for entry in parsed.entries[:max_results]:
            link = entry.get('link', '')
            title = entry.get('title', '').strip()
            snippet = entry.get('summary', '') or entry.get('description', '')
            pub = entry.get('published', '')
            source_feed = entry.get('source', {}).get('href', '')

            # 清理 HTML
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:200]

            # 提取域名
            domain = ''
            try:
                from urllib.parse import urlparse
                domain = urlparse(link).hostname or ''
            except Exception:
                pass

            if not title or not link:
                continue

            # 排除主雷达已有信源
            is_anchor = any(d in (domain + source_feed).lower() for d in ANCHOR_DOMAINS)
            if is_anchor:
                continue

            # 相关度过滤
            if not is_relevant(title, snippet, domain):
                continue

            items.append({
                'title': title,
                'url': link,
                'description': snippet,
                'source': f'今日头条: {keyword}',
                'site_name': domain or 'news.google.com',
                'date_str': pub[:10] if pub else None,
                'published_at': pub if pub else None,
            })

        print(f"  [OK] {keyword}: {len(items)} results")
        return items

    except Exception as e:
        print(f"  [FAIL] {keyword}: {e}")
        return []


def main():
    keywords = [
        "人形机器人",
        "具身智能",
        "物理AI",
        "脑机接口",
        "具身智能产业",
    ]

    print(f"[TOUTIAO] 开始抓取，今日头条专区")
    print(f"[TOUTIAO] 关键词: {keywords}")

    all_items = []
    seen_urls = set()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(search_toutiao, kw): kw for kw in keywords}
        for future in as_completed(futures):
            kw = futures[future]
            try:
                items = future.result()
                for item in items:
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        all_items.append(item)
            except Exception as e:
                print(f"  [ERROR] {kw}: {e}")

    print(f"\n[TOUTIAO] 总计: {len(all_items)} 条")

    # 按发布时间倒序
    all_items.sort(key=lambda x: x.get('published_at', '') or '', reverse=True)

    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'total_items': len(all_items),
        'items': all_items[:30],
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[TOUTIAO] 已保存到 {OUTPUT_FILE}: {len(all_items)} 条")

    # 显示前 10 条
    print("\n[TOUTIAO] 前 10 条结果:")
    for i, item in enumerate(all_items[:10], 1):
        print(f"  {i}. {item['title'][:60]}")
        print(f"     {item.get('site_name', 'N/A')}")


if __name__ == '__main__':
    main()