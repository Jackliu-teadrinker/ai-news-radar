#!/usr/bin/env python3
"""Bing 搜索抓取器 — 机器人/具身智能/脑机接口 实时资讯

用 Bing 搜索替代搜狗，抓取最新新闻到雷达搜索专区。
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
    "机器人 融资",
    "机器人 新闻",
]
SEARCH_MAX_PER_KW = 15  # 每关键词最多结果数
WINDOW_HOURS = 24       # 时间窗口（小时）

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'search-news.json')

# 搜索源权重（用于排序）
SOURCE_WEIGHT = {
    '新华社': 10,
    '新华网': 10,
    '人民网': 9,
    '央视': 9,
    '腾讯新闻': 7,
    '搜狐': 6,
    '网易': 6,
    '知乎': 5,
    '36氪': 8,
    '量子位': 8,
    '机器之心': 8,
    '雷锋网': 8,
}


def search_bing(keyword: str, max_results: int = 15) -> list[dict]:
    """搜索 Bing，返回结果列表。"""
    url = f"https://cn.bing.com/search?q={urllib.parse.quote(keyword)}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            print(f"  [FAIL] {keyword}: HTTP {resp.status_code}")
            return []
        
        # 提取搜索结果 - Bing 的结果在 <li class="b_algo"> 中
        results = re.findall(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
        
        items = []
        for result in results[:max_results]:
            # 提取链接
            link_match = re.search(r'<a[^>]*href="([^"]+)"[^>]*>', result)
            link = link_match.group(1) if link_match else ''
            
            # 提取标题 - 通常在 <h2> 中
            title_match = re.search(r'<h2[^>]*>(.*?)</h2>', result, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ''
            
            # 提取域名
            domain = ''
            domain_match = re.search(r'([\w-]+\.[\w.]+)', link)
            if domain_match:
                domain = domain_match.group(1)
            
            # 提取摘要 - 在 <p class="b_caption"> 或 <p> 中
            snippet_match = re.search(r'<p[^>]*class="b_caption"[^>]*>(.*?)</p>', result, re.DOTALL)
            if not snippet_match:
                snippet_match = re.search(r'<p[^>]*>(.*?)</p>', result, re.DOTALL)
            snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()[:200] if snippet_match else ''
            
            # 提取日期
            date_match = re.search(r'(\d{4}[-年]\d{1,2}[-月]\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2})', snippet)
            date_str = date_match.group(1) if date_match else None
            
            if title and link and 'javascript:' not in link:
                # 过滤掉百度文库等非新闻源
                if any(x in domain for x in ['baidu.com', 'zhuanlan.zhihu.com', 'tahou.com', 'openloong.net']):
                    continue
                
                items.append({
                    'title': title,
                    'url': link,
                    'description': snippet,
                    'source': f'Bing: {keyword}',
                    'site_name': domain,
                    'date_str': date_str,
                    'published_at': None,  # Bing 不提供标准时间戳
                })
        
        print(f"  [OK] {keyword}: {len(items)} results")
        return items
        
    except Exception as e:
        print(f"  [FAIL] {keyword}: {e}")
        return []


def get_source_weight(site_name: str) -> int:
    """获取来源权重。"""
    for key, weight in SOURCE_WEIGHT.items():
        if key in site_name:
            return weight
    return 1


def main():
    CST = timezone(timedelta(hours=8))
    now_sh = datetime.now(CST)
    window_start = now_sh - timedelta(hours=WINDOW_HOURS)
    
    print(f"[SEARCH] 开始搜索，窗口: {window_start.strftime('%Y-%m-%d %H:%M')} → {now_sh.strftime('%Y-%m-%d %H:%M')}")
    print(f"[SEARCH] 关键词: {SEARCH_KEYWORDS}")
    
    all_items = []
    seen_urls = set()
    
    # 并发搜索
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(search_bing, kw, SEARCH_MAX_PER_KW): kw for kw in SEARCH_KEYWORDS}
        for future in as_completed(futures):
            kw = futures[future]
            try:
                items = future.result()
                for item in items:
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        item['weight'] = get_source_weight(item.get('site_name', ''))
                        all_items.append(item)
            except Exception as e:
                print(f"  [ERROR] {kw}: {e}")
    
    print(f"\n[SEARCH] 总计: {len(all_items)} 条去重后结果")
    
    # 按权重和关键词匹配排序
    def sort_key(item):
        title = item['title'].lower()
        # 关键词匹配得分
        keyword_score = 0
        for kw in SEARCH_KEYWORDS:
            if kw in item['source']:
                keyword_score = 10
                break
        # 标题匹配得分
        robot_keywords = ['机器人', '人形', '具身', '物理AI', '脑机', 'AI']
        title_score = sum(1 for kw in robot_keywords if kw in title)
        return -(item['weight'] * 10 + keyword_score * 5 + title_score)
    
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
        print(f"     {item['url'][:60]}")
        print(f"     来源: {item['site_name']}")


if __name__ == '__main__':
    main()
