"""
翻译工具模块 — 供 arxiv_fetcher.py 和 government_fetcher.py 复用
提供中文翻译功能，带缓存和重试机制
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# 翻译缓存路径（相对于仓库根目录）
_CACHE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'title-zh-cache.json')


def is_english(text: str) -> bool:
    """Returns True if text is predominantly English (fewer than 20% Chinese chars)."""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    total = len(text.strip())
    return total > 0 and chinese / total < 0.2


def translate_text(text: str, target: str = 'zh', _retries: int = 3) -> str:
    """Translate text using Google Translate API (free, no key required).
    
    Uses exponential backoff retry for 429 rate limit responses.
    """
    if not text or not text.strip():
        return text
    
    # Check cache first
    cache = _load_cache()
    if text in cache and cache[text] and cache[text] != text:
        return cache[text]
    
    url = 'https://translate.googleapis.com/translate_a/single'
    params = {
        'client': 'gtx', 'sl': 'auto', 'tl': target,
        'dt': 't', 'q': text
    }
    
    last_exception = None
    for attempt in range(_retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Parse the response carefully
                if data and len(data) > 0 and data[0]:
                    translated = ''.join(item[0] for item in data[0] if item and len(item) > 0 and item[0])
                    if translated:
                        # Save to cache
                        cache = _load_cache()
                        cache[text] = translated
                        _save_cache(cache)
                        return translated
                return ''
            elif r.status_code == 429:
                # Rate limited — wait with exponential backoff then retry
                wait = (attempt + 1) * 2
                time.sleep(wait)
                continue
            else:
                return ''
        except Exception as e:
            last_exception = e
            if attempt == _retries - 1:
                print(f"[TRANSLATE] Failed after {attempt+1} attempts: {e}")
                return ''
            time.sleep(1)
    return ''


def translate_batch(texts: list[str], target: str = 'zh', max_workers: int = 2) -> dict[str, str]:
    """Translate multiple texts concurrently using Google Translate.
    Returns dict mapping original text to translated text.
    """
    if not texts:
        return {}
    
    # Load cache and filter out already translated
    cache = _load_cache()
    unknown_texts = [t for t in texts if t and t not in cache]
    
    if not unknown_texts:
        return cache
    
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in unknown_texts:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    
    results = dict(cache)  # Start with cached translations
    
    def _translate(text):
        return text, translate_text(text, target)
    
    actual_workers = min(max_workers, 2)
    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {executor.submit(_translate, t): t for t in unique}
        for future in as_completed(futures):
            try:
                orig, trans = future.result(timeout=15)
                results[orig] = trans
            except Exception as e:
                print(f"[TRANSLATE] Error translating '{orig[:30]}...': {e}")
    
    return results


def _load_cache() -> dict:
    """Load translation cache from JSON file."""
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    """Save translation cache to JSON file."""
    cache_dir = os.path.dirname(_CACHE_PATH)
    os.makedirs(cache_dir, exist_ok=True)
    with open(_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)