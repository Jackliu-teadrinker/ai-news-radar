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
# 2026-10-14: GoogleDecoder 实例复用（内部复用 httpx 连接池，别每次新建）
_decoder_inst = None


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
    real = None
    # 2026-10-14 BUGFIX: googlenewsdecoder 0.2.x 删除了 new_decoderv1，
    # 旧代码只调 new_decoderv1（AttributeError 被 except 吞掉）再退回
    # gnewsdecoder；而 0.2.1 的 gnewsdecoder 同样解不出（Google 改了
    # data 属性，函数返回 success=False / 无 decoded_url）。两条路径都失败
    # → decode_miss 接近 100% → 摘要永久为空（日志里 candidates=0/ok=0）。
    # 现在按可用入口依次尝试：GoogleDecoder 实例 → legacy gnewsdecoder。
    decoder_cls = getattr(_gnd, 'GoogleDecoder', None)
    if decoder_cls is not None:
        global _decoder_inst
        if _decoder_inst is None:
            try:
                _decoder_inst = decoder_cls(timeout=20, user_agent=USER_AGENT)
            except Exception:
                try:
                    _decoder_inst = decoder_cls(timeout=20)
                except Exception:
                    _decoder_inst = False
        if _decoder_inst:
            try:
                r = _decoder_inst.decode_google_news_url(gn_url)
                if isinstance(r, dict):
                    real = r.get('decoded_url') or r.get('url')
                    if not real and not r.get('success', True):
                        real = None
            except Exception:
                real = None
    if not real:
        try:
            r2 = _gnd.gnewsdecoder(gn_url)
            if isinstance(r2, dict):
                real = r2.get('decoded_url') or r2.get('url')
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
            real, headers={'User-Agent': USER_AGENT,
                           'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'},
            timeout=FETCH_TIMEOUT, allow_redirects=True, verify=False,
        )
        text = trafilatura.extract(
            resp.content, include_comments=False,
            include_tables=False, with_metadata=False,
        )
        # GBK 编码兜底（部分国内站 resp.encoding 判错）
        if not text or len(text.strip()) < MIN_BODY_LEN:
            try:
                text = trafilatura.extract(
                    resp.content.decode('gb18030', errors='ignore').encode('utf-8'),
                    include_comments=False, include_tables=False, with_metadata=False)
            except Exception:
                pass
    except Exception:
        return ''
    # 部分源 sohu 等返回 200 但首抓偶发空/JS 壳：换移动版域名重试一次
    if not text or len(text.strip()) < MIN_BODY_LEN:
        host = urlparse(real).netloc
        mobile_map = {'www.sohu.com': 'm.sohu.com', 'm.sohu.com': 'www.sohu.com',
                      'finance.sina.com.cn': 'finance.sina.cn', 'www.sina.com.cn': 'sina.cn'}
        alt_host = mobile_map.get(host)
        if alt_host:
            alt_url = re.sub(re.escape(host), alt_host, real, count=1)
            try:
                resp2 = requests.get(
                    alt_url, headers={'User-Agent': USER_AGENT,
                                      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'},
                    timeout=FETCH_TIMEOUT, allow_redirects=True, verify=False)
                text2 = trafilatura.extract(
                    resp2.content, include_comments=False,
                    include_tables=False, with_metadata=False)
                if text2 and len(text2.strip()) > len((text or '').strip()):
                    text = text2
            except Exception:
                pass
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


def enrich_items(items: list, output_dir: str, top_n: int = 150, recheck: bool = False) -> dict:
    """给 items 补 description（120 字真摘要）。就地修改 item dict。

    只处理：url 是 GN 跳转 且 description 为空/复读的条目；
    按 total_score 取 top_n；并发解码+抓取。返回统计 dict。

    recheck=True: 已有 ≥30 字摘要且未成功抓过(无标记)的条目也重新抓取
      （用于本地/CI 校验真实覆盖；每 12min 定时刷新仍默认 recheck=False，只补空）。
    """
    stats = {'candidates': 0, 'ok': 0, 'failed': 0, 'decode_miss': 0, 'elapsed_s': 0.0}
    if trafilatura is None or _gnd is None:
        print('[SUMMARY] enricher deps missing (trafilatura/googlenewsdecoder), skip')
        return stats

    cache_path = os.path.join(output_dir, 'gn-url-cache.json')
    cache = _load_cache(cache_path)

    def _needs(i):
        d = (i.get('description') or '').strip()
        if not _is_gn_url(i.get('url', '')):
            return False
        if len(d) < 30:
            return True
        return recheck and not i.get('_summary_ok')

    cands = [i for i in items if _needs(i)]
    cands.sort(key=lambda x: -x.get('total_score', 0))
    cands = cands[:min(top_n, MAX_CANDIDATES)]
    stats['candidates'] = len(cands)
    # 2026-10-14 诊断：candidates 恒为 0 是"输入就没进去"的信号，过去静默 return。
    # 打印输入规模 + 为什么没进队列，让 CI 日志能直接定位。
    _gn = sum(1 for i in items if _is_gn_url(i.get('url','')))
    _empty = sum(1 for i in items if len((i.get('description') or '').strip()) < 30)
    _notdict = sum(1 for i in items if not isinstance(i, dict))
    print(f"[SUMMARY] input: total={len(items)} gn_urls={_gn} desc<30={_empty} "
          f"non_dict={_notdict} -> candidates={len(cands)} (top_n={top_n}, recheck={recheck})")
    if not cands and _notdict:
        print(f"[SUMMARY] 输入含 {_notdict} 个非 dict 元素（期望 item dict，可能是顶层 dict 未解包）")
    if not cands:
        # 2026-10-14: candidates=0 过去是静默 return stats，日志里只留一行
        # "candidates: 0"，看起来像"没有需要补的"（正常），实际是全站摘要
        # 集体失效的信号。改成显式告警，避免再次静默。
        print('[SUMMARY] candidates=0 —— 没有条目进入补摘要队列。'
              '若同时 decode_miss 也为 0，多半是上游解码器失效（GN 跳转解析），'
              '不是"摘要已齐"，请检查 googlenewsdecoder 版本。')
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

    # 阶段 2: 并发抓正文（按 url 去重，同一真实 URL 只抓一次；缓存命中也重抓一次正文）
    need_fetch = [i for i in cands if urls.get(i['url'])]
    seen, uniq = set(), []
    for i in need_fetch:
        u = urls[i['url']]
        if u not in seen:
            seen.add(u)
            uniq.append(i)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = [ex.submit(_make_description, i, cache, cache_path) for i in uniq]
        results = []
        for f, item in zip(futs, uniq):
            try:
                s = f.result()
            except Exception:
                s = ''
            results.append((item, s))
        by_url = {item['url']: s for item, s in results}
    for item in need_fetch:
        s = by_url.get(item['url'], '')
        if s:
            item['description'] = s[:300]
            item.pop('_summary_ok', None)
            item['_summary_ok'] = True
            stats['ok'] += 1
        else:
            stats['failed'] += 1
    stats['elapsed_s'] = round(time.time() - t0, 1)
    print(f"[SUMMARY] enriched {stats['ok']}/{stats['candidates']} "
          f"(decode_miss={miss}, failed={stats['failed']}, {stats['elapsed_s']}s, recheck={recheck})")
    return stats


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv[1:]) else 'data'
    if len(sys.argv) >= 4 and sys.argv[1] == '--items':
        # 子进程隔离模式（2026-09-30）：enrich_items 会调 trafilatura/lxml C 扩展，
        # 高并发抓正文时偶发 glibc 堆损坏 → SIGABRT（exit 134），主管线 try/except
        # 接不住 C 层 abort。update_news.py 现在在子进程里跑本 CLI：
        #   python summary_enricher.py --items <items.json> <output_dir> <top_n> [recheck]
        # 崩溃只死子进程，主流程降级跳过摘要，数据照常落地。
        items_path, odir, top_n = sys.argv[2], sys.argv[3], int(sys.argv[4])
        recheck = (sys.argv[5] == '1') if len(sys.argv) > 5 else False
        with open(items_path, encoding='utf-8') as f:
            items = json.load(f)
        st = enrich_items(items, odir, top_n=top_n, recheck=recheck)
        # 写回（子进程崩溃时主流程拿不到写回文件 → 判为失败降级）
        tmp = items_path + '.enriched'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, items_path)
        print(f"[SUMMARY-CLI] done: {st}")
    else:
        # 独立运行：对 data/latest-24h-min.json 补摘要
        p = os.path.join(out, 'latest-24h-min.json')
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        st = enrich_items(d.get('items_ai', []), out, top_n=150)
        print(st)
