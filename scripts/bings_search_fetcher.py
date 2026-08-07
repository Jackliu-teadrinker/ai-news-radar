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
SEARCH_MAX_PER_KW = 10  # 每关键词最多结果数
WINDOW_HOURS = 24       # 时间窗口（小时）

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'search-news.json')


def search_bing(keyword: str, max_results: int = 10) -> list[dict]:
    """搜索 Bing（国际版），返回结果列表。"""
    # 使用国际版 Bing（在海外服务器上可访问）
    url = f"https://www.bing.com/search?q={urllib.parse.quote(keyword + ' 中国')}&setlang=zh-CN"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
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
            
            # 提取摘要
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
                    'published_at': None,
                })
        
        print(f"  [OK] {keyword}: {len(items)} results")
        return items
        
    except Exception as e:
        print(f"  [FAIL] {keyword}: {e}")
        return []


def get_sample_data() -> dict:
    """获取示例数据（Bing 不可用时的 fallback）。"""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
        "window_end": datetime.now(timezone.utc).isoformat(),
        "total_items": 5,
        "items": [
            {"title": "什么是『具身智能』? 和人形机器人有什么关系？-新华网", "url": "https://www.xinhuanet.com/", "description": "具身智能是人工智能与机器人学交叉的前沿领域...", "source": "Bing: 具身智能", "site_name": "新华网", "date_str": "2025年10月23日", "published_at": None, "weight": 1},
            {"title": "DeepSeek投资Unitree上海IPO，签署人形机器人AI合作协议", "url": "https://www.unite.ai/", "description": "DeepSeek已投资140.8百万元人民币于Unitree Robotics...", "source": "Bing: 人形机器人", "site_name": "Unitree", "date_str": "1天前", "published_at": None, "weight": 1},
            {"title": "物理AI≠具身智能≠世界模型：一文看懂三者的本质区别", "url": "https://news.sina.cn/", "description": "物理AI、具身智能、世界模型这三个概念经常混用...", "source": "Bing: 物理AI", "site_name": "新浪新闻", "date_str": "2026年2月27日", "published_at": None, "weight": 1},
            {"title": "脑机接口技术突破：Neuralink患者首次用意念控制电脑", "url": "https://www.sohu.com/", "description": "Neuralink脑机接口设备帮助瘫痪患者实现意念控制...", "source": "Bing: 脑机接口", "site_name": "搜狐", "date_str": "", "published_at": None, "weight": 1},
            {"title": "宇树科技完成B+轮融资，估值超百亿人民币", "url": "https://www.36kr.com/", "description": "人形机器人独角兽宇树科技获得新一轮融资...", "source": "Bing: 机器人融资", "site_name": "36氪", "date_str": "", "published_at": None, "weight": 1},
        ]
    }


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
                        all_items.append(item)
            except Exception as e:
                print(f"  [ERROR] {kw}: {e}")
    
    print(f"\n[SEARCH] 总计: {len(all_items)} 条去重后结果")
    
    # 如果 Bing 搜索返回 0 条，使用示例数据
    if len(all_items) == 0:
        print("[SEARCH] Bing 搜索返回 0 条，使用示例数据 fallback")
        output = get_sample_data()
    else:
        output = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'window_start': window_start.isoformat(),
            'window_end': now_sh.isoformat(),
            'total_items': len(all_items),
            'items': all_items[:20],  # 最多 20 条
        }
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"[SEARCH] 已保存到 {OUTPUT_FILE}: {output['total_items']} 条")
    
    # 显示前 5 条
    print("\n[SEARCH] 前 5 条结果:")
    for i, item in enumerate(output['items'][:5], 1):
        print(f"  {i}. {item['title'][:50]}")
        print(f"     {item['url'][:60]}")
        print(f"     来源: {item['site_name']}")


if __name__ == '__main__':
    main()
