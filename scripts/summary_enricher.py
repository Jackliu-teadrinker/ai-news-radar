#!/usr/bin/env python3
"""Summary Enricher — GN 跳转链接解码 → 真实 URL → trafilatura 抓正文 → 120 字摘要

Jack 2026-09-11: 目标展示格式 = 新闻价值分数 + 标题 + 120 字摘要。
GN (Google News) RSS 的 description 字段是"标题+来源"复读（被 clean_description 清掉），
所以主 feed / 锚点 99% 条目摘要为空。本模块补齐真摘要：

  1. news.google.com/rss/articles/CBxx 跳转链接 → googlenewsdecoder 解出真实来源 URL
     （首次解码需访问 Google 一次；结果缓存 data/gn-url-cache.json，后续刷新 0 网络开销）
  2. requests 抓真实 URL 正文 → trafilatura 强提取 → 前 ~120 字（句界截断）
  3. 抓不到/太短 → 保持原 description 不动（前端降级为只显示 分数+标题，不留空白占位）

用法（update_news.py 在 write min.json 前调用）：
    from summary_enricher import enrich_items
    scored = enrich_items(scored, output_dir, top_n=150)

依赖：googlenewsdecoder, trafilatura, requests（requirements.txt 已加）
"""
import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    import googlenewsdecoder as _gnd
except ImportError:
    _gnd = None

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
FETCH_TIMEOUT = 15
DECODE_WORKERS = 8
FETCH_WORKERS = 10
MIN_BODY_LEN = 80      # 正文 < 80 字视为抓取失败，不降级填充
TARGET_LEN = 120       # Jack 目标：120 字词摘要
MAX_CANDIDATES = 300   # 单次刷新参与 enrich 的候选上限（top 分数优先）

_lock = threading.Lock()


def _is_gn_url(url: str) -> bool:
    return bool(url) and 'news.google.com' in url and '/rss/articles/' in url


def _load_cache(cache_path: str) -> dict:
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache_path: str, cache: dict) -> None:
    tmp = cache_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cache_path)


def _decode_gn_url(gn_url: str, cache: dict, cache_path: str) -> str:
    """GN 跳转链接 → 真实来源 URL（缓存命中直接返回）。"""
    with _lock:
        if cache.get(gn_url):
            return cache[gn_url]
    if _gnd is None:
        return ''
    try:
        r = _gnd.new_decoderv1(gn_url)
        real = r.get('decoded_url') if isinstance(r, dict) else None
    except Exception:
        real = None
    if not real:
        try:
            r2 = _gnd.gnewsdecoder(gn_url)
            real = r2.get('decoded_url') if isinstance(r2, dict) else None
        except Exception:
            real = None
    if real and real.startswith('http'):
        real = real.rstrip('?')
        with _lock:
            cache[gn_url] = real
        return real
    return ''


_BOILER_PAT = re.compile(
    r'(\d{4}[-/年.]\s?\d{1,2}[-/月.]\s?\d{0,2}|^\d{1,2}:\d{2}(?::\d{2})?|直播|你永远在|\d+\s?x\s?24|来源[:：]|记者\s*\S|摄影|责任编辑|编辑[:：]|责任编辑)',
    re.I)


def _dedup_title_prefix(desc: str, title: str) -> str:
    """去掉摘要开头复述标题的部分（trafilatura 常把 <h1> 抓进正文）。

    稳版：取标题尾段（去尾 " - 来源"/"|标签" 后的末 10 个有效字符）在
    desc 中定位；命中则截到其后，再跳 1 个短来源词（≤10 字）。
    截完不足 30 字则放弃（避免误伤）。
    """
    d = (desc or '').strip()
    t = (title or '').strip()
    if not d or not t:
        return d
    t_main = re.sub(r'\s*[-–—]\s*[^-–—|｜\s]{1,30}$', '', t)  # 尾 " - 虎嗅网"
    t_main = re.split(r'[|｜]', t_main)[0].strip()             # 尾 "|世界模型"
    if len(t_main) < 6:
        return d
    tail = t_main[-10:]
    di = d.find(tail)
    if di < 0:
        return d
    rest = d[di + len(tail):].lstrip(' \t　-–—|｜')
    # 再跳 1 个短来源词（如 "虎嗅网"），仅在剩余仍 ≥30 字时
    m2 = re.match(r'^[^\s。！？，、]{1,10}(\s+)', rest)
    if m2:
        rest2 = rest[m2.end():].lstrip()
        if len(rest2) >= 30:
            rest = rest2
    return rest if len(rest) >= 30 else d


def _cut_summary(body: str, target: int = TARGET_LEN) -> str:
    """正文 → 前 target 字摘要：句界截断（保留句末标点）+ 跳过站方样板句。"""
    body = re.sub(r'\s+', ' ', (body or '').strip())
    if not body:
        return ''
    sents = [m.group(0).strip() for m in re.finditer(r'[^。！？\n]+[。！？]', body)]
    tail_rest = re.sub(r'.*[。！？]', '', body).strip()
    sents = [s for s in sents if s]
    if tail_rest and len(tail_rest) >= 12:
        sents.append(tail_rest)
    if not sents:
        sents = [body]
    kept = [s for s in sents if len(s) >= 12 and not _BOILER_PAT.search(s[:24])]
    if not kept:
        kept = sents
    out = ''
    for s in kept:
        cand = out + s
        if len(cand) > target + 30 and out:
            break
        out = cand
        if len(out) >= target:
            break
    s = out.strip()
    if len(s) > target + 10:
        s = s[:target]
    return s


def _make_description(item: dict, cache: dict, cache_path: str) -> str:
    """单条 item → 120 字摘要；失败返回 ''（保持原状）。"""
    gn_url = item.get('url', '')
    if not _is_gn_url(gn_url):
        return ''
    real = _decode_gn_url(gn_url, cache, cache_path)
    if not real:
        return ''
    if not real.startswith('http'):
        return ''
    try:
        resp = requests.get(
            real, headers={'User-Agent': USER_AGENT},
            timeout=FETCH_TIMEOUT, allow_redirects=True, verify=False,
        )
        text = trafilatura.extract(
            resp.content, include_comments=False,
            include_tables=False, with_metadata=False,
        )
    except Exception:
        return ''
    if not text or len(text.strip()) < MIN_BODY_LEN:
        return ''
    # 垃圾正文检测（反爬/403/验证码页）
    head = text.strip()[:200].lower()
    for bad in ('access denied', '403 forbidden', 'you don\'t have permission',
                'unauthorized', 'enable javascript', 'please enable cookies',
                '验证', 'captcha', 'page not found', '404'):
        if bad in head:
            return ''
    # 正文开头常复述 <h1> 标题 → 剥掉后再截 120 字，避免摘要 = 标题复读
    body = _dedup_title_prefix(text, item.get('title', ''))
    if len(body.strip()) < MIN_BODY_LEN:
        return ''
    return _cut_summary(body)


def enrich_items(items: list, output_dir: str, top_n: int = 150) -> dict:
    """给 items 补 description（120 字真摘要）。就地修改 item dict。

    只处理：url 是 GN 跳转 且 description 为空/复读的条目；
    按 total_score 取 top_n；并发解码+抓取。返回统计 dict。
    """
    stats = {'candidates': 0, 'ok': 0, 'failed': 0, 'decode_miss': 0, 'elapsed_s': 0.0}
    if trafilatura is None or _gnd is None:
        print('[SUMMARY] enricher deps missing (trafilatura/googlenewsdecoder), skip')
        return stats

    cache_path = os.path.join(output_dir, 'gn-url-cache.json')
    cache = _load_cache(cache_path)

    cands = [i for i in items
             if _is_gn_url(i.get('url', '')) and len((i.get('description') or '').strip()) < 30]
    cands.sort(key=lambda x: -x.get('total_score', 0))
    cands = cands[:min(top_n, MAX_CANDIDATES)]
    stats['candidates'] = len(cands)
    if not cands:
        return stats

    t0 = time.time()
    # 阶段 1: 并发解码 GN URL（缓存命中为 0 开销）
    urls = {}
    with ThreadPoolExecutor(max_workers=DECODE_WORKERS) as ex:
        futs = {ex.submit(_decode_gn_url, i['url'], cache, cache_path): i['url'] for i in cands}
        for f in futs:
            u = futs[f]
            try:
                urls[u] = f.result()
            except Exception:
                urls[u] = ''
    miss = sum(1 for u in urls.values() if not u)
    stats['decode_miss'] = miss
    _save_cache(cache_path, cache)

    # 阶段 2: 并发抓正文（跳过已解出 URL 的缓存部分也要抓——description 可能仍是复读清洗后的空）
    need_fetch = [i for i in cands if urls.get(i['url'])]
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = [ex.submit(_make_description, i, cache, cache_path) for i in need_fetch]
        for f, item in zip(futs, need_fetch):
            try:
                s = f.result()
            except Exception:
                s = ''
            if s:
                item['description'] = s[:300]
                stats['ok'] += 1
            else:
                stats['failed'] += 1
    stats['elapsed_s'] = round(time.time() - t0, 1)
    print(f"[SUMMARY] enriched {stats['ok']}/{stats['candidates']} "
          f"(decode_miss={miss}, failed={stats['failed']}, {stats['elapsed_s']}s)")
    return stats


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else 'data'
    # 独立运行：对 data/latest-24h-min.json 补摘要
    p = os.path.join(out, 'latest-24h-min.json')
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    st = enrich_items(d.get('items_ai', []), out, top_n=150)
    print(st)
