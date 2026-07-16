#!/usr/bin/env python3
"""
微信公众号文章采集器

数据来源（优先级从高到低）：
1. wechat-manual.json — 用户手动添加的文章
2. wechat-articles.json — 雷达数据中的微信文章（用于兼容旧格式）

这些文章跳过 RSS 时间窗口过滤，直接合并到最终输出中。
"""

import json
import os
import re
import hashlib
from datetime import datetime, timedelta, timezone


def _load_json(path: str) -> list:
    """安全加载 JSON 文件"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and 'articles' in data:
            return data['articles']
        return []
    except Exception:
        return []


def _fetch_wechat_pub_time(url: str) -> str | None:
    """
    抓取微信公众号文章的真实发布时间。
    
    微信公众号页面中，发布时间通常以 'YYYY-MM-DD HH:MM' 格式出现在 HTML 中。
    返回 ISO 格式字符串（UTC），如果抓取失败返回 None。
    """
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        # 查找 'YYYY-MM-DD HH:MM' 格式的时间
        m = re.search(r'(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2})', html)
        if m:
            dt_str = m.group(1)
            # 微信文章时间是北京时间（UTC+8）
            dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            return dt.astimezone(timezone.utc).isoformat()
        
        # 备选：查找其他时间格式
        m2 = re.search(r'(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', html)
        if m2:
            dt = datetime.fromisoformat(m2.group(1))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            return dt.astimezone(timezone.utc).isoformat()
        
    except Exception:
        pass
    return None


def _normalize_wechat_item(raw: dict, url: str = None) -> dict:
    """将手动添加的文章格式标准化为雷达统一格式"""
    url = url or raw.get('url', '')
    title = raw.get('title', '未知文章')
    
    # 生成稳定 ID
    item_id = hashlib.sha1(url.encode()).hexdigest()[:32]
    
    # 尝试抓取真实发布时间
    real_published_at = _fetch_wechat_pub_time(url)
    
    # 优先使用真实抓取的时间，fallback 到 raw 中的 published_at
    if real_published_at:
        pub_str = real_published_at
    else:
        pub_str = raw.get('published_at', '')
        if not pub_str:
            pub_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    
    try:
        pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
    except Exception:
        pub_dt = datetime.now(timezone.utc)
    
    return {
        'id': item_id,
        'title': title,
        'title_zh': '',
        'url': url,
        'published_at': pub_dt.isoformat(),
        'category': '微信公众号',
        'gn_label': 'wechat',
        'site_name': raw.get('source', '微信公众号'),
        'source': '微信公众号',
        'site_id': 'wechat',
        'description': raw.get('description', raw.get('notes', '')),
        'ai_score': raw.get('ai_score', 90),
        'ai_label': raw.get('ai_label', '高价值'),
        'relevance': raw.get('relevance', raw.get('ai_score', 90)) / 100,
        'authority': raw.get('authority', 80),
        'depth': raw.get('depth', 85),
        'timeliness': raw.get('timeliness', 100),
        'writing_value': raw.get('writing_value', 85),
        'total_score': raw.get('total_score', raw.get('ai_score', 90)),
    }


def collect_wechat_articles(
    keywords: list = None,
    hours: int = 24,
    max_per_keyword: int = 10,
    include_manual: bool = True,
) -> list:
    """
    收集微信公众号文章。
    
    Args:
        keywords: 搜索关键词（暂未启用 Exa 搜索，预留接口）
        hours: 搜索时间范围（暂未启用）
        max_per_keyword: 每关键词最大结果（暂未启用）
        include_manual: 是否包含 wechat-manual.json 中的手动添加文章
    
    Returns:
        标准化的微信文章列表
    """
    articles = []
    
    # 1. 加载 data/wechat-manual.json（首选来源，相对于脚本目录）
    if include_manual:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(script_dir, '..', 'data')
        manual_path = os.path.join(data_dir, 'wechat-manual.json')
        manual_data = _load_json(manual_path)
        for raw in manual_data:
            if raw.get('url') and raw.get('title'):
                normalized = _normalize_wechat_item(raw, url=raw['url'])
                articles.append(normalized)
        print(f"[WECHAT] Loaded {len(manual_data)} articles from {manual_path}")
    
    # 2. 加载 wechat-articles.json（兼容旧格式，去重用）
    data_dir = os.path.join(script_dir, '..', 'data')
    legacy_path = os.path.join(data_dir, 'wechat-articles.json')
    legacy_data = _load_json(legacy_path)
    
    # 用 URL 去重，保留最新数据
    existing_urls = {a['url'] for a in articles}
    for raw in legacy_data:
        if raw.get('url') not in existing_urls:
            normalized = _normalize_wechat_item(raw, url=raw['url'])
            articles.append(normalized)
    
    # 按时间排序（最新在前）
    articles.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    
    return articles


if __name__ == '__main__':
    arts = collect_wechat_articles(include_manual=True)
    print(f'[WECHAT-COLLECTOR] Collected {len(arts)} articles')
    for a in arts:
        print(f"  - {a['title'][:50]} | {a['published_at']} | {a.get('total_score', 'N/A')}")
