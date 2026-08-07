#!/usr/bin/env python3
"""搜索专区抓取器 — 今日头条、微信公众号等中国本土信源

收集中国本土平台的机器人/具身智能相关资讯，补充 Google News 的不足。
输出到 data/search-news.json，供前端展示。
"""
import os
import re
import sys
import json
import time
import urllib.parse
import urllib3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
SEARCH_KEYWORDS = [
    "人形机器人",
    "具身智能",
    "物理AI",
    "脑机接口",
    "机器人融资",
    "机器人新闻",
]
SEARCH_MAX_PER_KW = 15  # 每关键词最多结果数
WINDOW_HOURS = 24       # 时间窗口（小时）

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'search-news.json')

# 信源配置
SOURCES = {
    '36氪': {
        'url': 'https://36kr.com/search/articles/{keyword}',
        'check': lambda html: '36kr.com' in html,
    },
    '量子位': {
        'url': 'https://www.qbitai.com/?s={keyword}',
        'check': lambda html: 'qbitai' in html,
    },
    '机器之心': {
        'url': 'https://www.jiqizhixin.com/search?query={keyword}',
        'check': lambda html: 'jiqizhixin' in html,
    },
}


def search_toutiao(keyword: str, max_results: int = 15) -> list[dict]:
    """搜索今日头条（通过 Google News 代理）。"""
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword + ' 今日头条')}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml',
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            return []
        
        # 解析 RSS
        import feedparser
        parsed = feedparser.parse(resp.text)
        
        items = []
        for entry in parsed.entries[:max_results]:
            link = entry.get('link', '')
            title = entry.get('title', '').strip()
            snippet = entry.get('summary', '') or entry.get('description', '')
            
            # 清理 HTML
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:200]
            
            # 检查是否包含今日头条内容
            if 'toutiao' in link.lower() or '今日' in title:
                items.append({
                    'title': title,
                    'url': link,
                    'description': snippet,
                    'source': f'今日头条: {keyword}',
                    'site_name': '今日头条',
                    'date_str': None,
                    'published_at': None,
                })
        
        if items:
            print(f"  [OK] 头条:{keyword}: {len(items)} results")
        return items
        
    except Exception as e:
        print(f"  [FAIL] 头条:{keyword}: {e}")
        return []


def search_wechat(keyword: str, max_results: int = 10) -> list[dict]:
    """搜索微信公众号文章（通过 Google News 代理）。"""
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword + ' site:mp.weixin.qq.com')}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml',
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            return []
        
        import feedparser
        parsed = feedparser.parse(resp.text)
        
        items = []
        for entry in parsed.entries[:max_results]:
            link = entry.get('link', '')
            title = entry.get('title', '').strip()
            snippet = entry.get('summary', '') or entry.get('description', '')
            
            # 清理 HTML
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:200]
            
            # 只保留微信公众号文章
            if 'mp.weixin.qq.com' in link:
                items.append({
                    'title': title,
                    'url': link,
                    'description': snippet,
                    'source': f'微信公众号: {keyword}',
                    'site_name': '微信公众号',
                    'date_str': None,
                    'published_at': None,
                })
        
        if items:
            print(f"  [OK] 微信:{keyword}: {len(items)} results")
        return items
        
    except Exception as e:
        print(f"  [FAIL] 微信:{keyword}: {e}")
        return []


def search_36kr(keyword: str, max_results: int = 10) -> list[dict]:
    """搜索36氪文章。"""
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword + ' site:36kr.com')}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml',
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            return []
        
        import feedparser
        parsed = feedparser.parse(resp.text)
        
        items = []
        for entry in parsed.entries[:max_results]:
            link = entry.get('link', '')
            title = entry.get('title', '').strip()
            snippet = entry.get('summary', '') or entry.get('description', '')
            
            # 清理 HTML
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:200]
            
            # 只保留36氪文章
            if '36kr.com' in link:
                items.append({
                    'title': title,
                    'url': link,
                    'description': snippet,
                    'source': f'36氪: {keyword}',
                    'site_name': '36氪',
                    'date_str': None,
                    'published_at': None,
                })
        
        if items:
            print(f"  [OK] 36氪:{keyword}: {len(items)} results")
        return items
        
    except Exception as e:
        print(f"  [FAIL] 36氪:{keyword}: {e}")
        return []


def search_jiqizhixin(keyword: str, max_results: int = 10) -> list[dict]:
    """搜索机器之心文章。"""
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword + ' site:jiqizhixin.com')}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml',
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            return []
        
        import feedparser
        parsed = feedparser.parse(resp.text)
        
        items = []
        for entry in parsed.entries[:max_results]:
            link = entry.get('link', '')
            title = entry.get('title', '').strip()
            snippet = entry.get('summary', '') or entry.get('description', '')
            
            # 清理 HTML
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:200]
            
            # 只保留机器之心文章
            if 'jiqizhixin' in link.lower():
                items.append({
                    'title': title,
                    'url': link,
                    'description': snippet,
                    'source': f'机器之心: {keyword}',
                    'site_name': '机器之心',
                    'date_str': None,
                    'published_at': None,
                })
        
        if items:
            print(f"  [OK] 机心:{keyword}: {len(items)} results")
        return items
        
    except Exception as e:
        print(f"  [FAIL] 机心:{keyword}: {e}")
        return []


def main():
    CST = timezone(timedelta(hours=8))
    now_sh = datetime.now(CST)
    window_start = now_sh - timedelta(hours=WINDOW_HOURS)
    
    print(f"[SEARCH] 开始搜索，窗口: {window_start.strftime('%Y-%m-%d %H:%M')} → {now_sh.strftime('%Y-%m-%d %H:%M')}")
    print(f"[SEARCH] 关键词: {SEARCH_KEYWORDS}")
    
    all_items = []
    seen_urls = set()
    
    # 并发搜索各信源
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}
        
        # 为每个关键词创建搜索任务
        for kw in SEARCH_KEYWORDS:
            futures[executor.submit(search_toutiao, kw)] = f'头条:{kw}'
            futures[executor.submit(search_wechat, kw)] = f'微信:{kw}'
            futures[executor.submit(search_36kr, kw)] = f'36氪:{kw}'
            futures[executor.submit(search_jiqizhixin, kw)] = f'机心:{kw}'
        
        # 收集结果
        for future in as_completed(futures):
            tag = futures[future]
            try:
                items = future.result()
                for item in items:
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        all_items.append(item)
            except Exception as e:
                print(f"  [ERROR] {tag}: {e}")
    
    print(f"\n[SEARCH] 总计: {len(all_items)} 条去重后结果")
    
    # 按来源和关键词排序
    def sort_key(item):
        source = item.get('source', '')
        # 优先显示微信公众号和36氪
        if '微信' in source:
            return 0
        elif '36氪' in source:
            return 1
        elif '头条' in source:
            return 2
        elif '机心' in source:
            return 3
        return 4
    
    all_items.sort(key=sort_key)
    
    # 输出
    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'window_start': window_start.isoformat(),
        'window_end': now_sh.isoformat(),
        'total_items': len(all_items),
        'items': all_items[:50],  # 最多 50 条
    }
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"[SEARCH] 已保存到 {OUTPUT_FILE}: {len(all_items)} 条")
    
    # 显示前 10 条
    print("\n[SEARCH] 前 10 条结果:")
    for i, item in enumerate(all_items[:10], 1):
        print(f"  {i}. {item['title'][:50]}")
        print(f"     {item['source']}")


if __name__ == '__main__':
    main()
