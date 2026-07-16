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
import hashlib
from datetime import datetime, timezone


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


def _normalize_wechat_item(raw: dict) -> dict:
    """将手动添加的文章格式标准化为雷达统一格式"""
    url = raw.get('url', '')
    title = raw.get('title', '未知文章')
    
    # 生成稳定 ID
    item_id = hashlib.sha1(url.encode()).hexdigest()[:32]
    
    now = datetime.now(timezone.utc)
    pub_str = raw.get('published_at', now.strftime('%Y-%m-%dT%H:%M:%S+00:00'))
    try:
        pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
    except Exception:
        pub_dt = now
    
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
    
    # 1. 加载 wechat-manual.json（首选来源）
    if include_manual:
        manual_path = os.path.expanduser('~/.hermes/wechat-manual.json')
        manual_data = _load_json(manual_path)
        for raw in manual_data:
            if raw.get('url') and raw.get('title'):
                normalized = _normalize_wechat_item(raw)
                articles.append(normalized)
    
    # 2. 加载 wechat-articles.json（兼容旧格式，去重用）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '..', 'data')
    legacy_path = os.path.join(data_dir, 'wechat-articles.json')
    legacy_data = _load_json(legacy_path)
    
    # 用 URL 去重，保留最新数据
    existing_urls = {a['url'] for a in articles}
    for raw in legacy_data:
        if raw.get('url') not in existing_urls:
            normalized = _normalize_wechat_item(raw)
            articles.append(normalized)
    
    # 按时间排序（最新在前）
    articles.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    
    return articles


if __name__ == '__main__':
    arts = collect_wechat_articles(include_manual=True)
    print(f'[WECHAT-COLLECTOR] Collected {len(arts)} articles')
    for a in arts:
        print(f"  - {a['title'][:50]} | {a['published_at']} | {a.get('total_score', 'N/A')}")
