#!/usr/bin/env python3
"""聚宽回测专区抓取器 — JoinQuant 社区策略库 + 主题优化（止损/仓位/轮动等）

数据源：https://www.joinquant.com/view/community/list?listType=4&type=isNew&tags=
真实 API（逆向自前端 main.bundle.js 的 chunk）：
    GET /community/post/listV2?page=N&limit=20&cate=X&word=&type=isNew&tags=&ajax=1
说明：
  - 缺 `ajax=1` 时返回 code=20000「系统异常」，必须带上。
  - cate=14「精华」（listType=4）、cate=3「文章」（listType=1）。
  - `word=` 关键词搜索可用但结果混入置顶噪声；本脚本不依赖 word，
    而是抓取文章分类最新页后，用本地关键词表给条目打主题标签
    （止损/仓位/网格/轮动/多因子/择时/动量/均值回归/机器学习/ETF/高频/期货）。
  - 列表按最近活跃排序（lastActiveTime），前几条多为置顶老文；
    按 addTime 过滤出近 WINDOW_DAYS 天内发布的条目。
  - 条目 URL = https://www.joinquant.com/view/community/detail/<postId>

输出：data/joinquant-news.json
"""
import os
import re
import sys
import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'joinquant-news.json')

BASE = "https://www.joinquant.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERER = BASE + "/view/community/list?listType=4&type=isNew&tags="

# 双分类：文章（量大、新）+ 精华（质量高）
CATEGORIES = [
    {"cate": "3",  "label": "文章", "pages": 3},
    {"cate": "14", "label": "精华", "pages": 1},
]

# 时间窗口：近 N 天内发布的策略
WINDOW_DAYS = 7
PAGE_LIMIT = 20
MAX_ITEMS = 30          # 输出上限
TOPIC_LIMIT = 3         # 每条最多展示 3 个主题标签

# 主题关键词表 — 命中标题/摘要即打标（顺序=展示优先级）
TOPIC_KEYWORDS = [
    ("止损",     ["止损", "stop loss"]),
    ("仓位",     ["仓位", "加仓", "减仓", "资金管理", "凯利"]),
    ("网格",     ["网格"]),
    ("轮动",     ["轮动", "rotation"]),
    ("多因子",   ["多因子", "因子", "factor", "IC"]),
    ("择时",     ["择时", "趋势", "均线", "MACD", "KDJ", "布林"]),
    ("动量",     ["动量", "momentum"]),
    ("均值回归", ["均值回归", "配对", "zscore", "配对交易"]),
    ("机器学习", ["机器学习", "LSTM", "强化学习", "深度学习", "XGBoost"]),
    ("ETF",     ["ETF", "大类资产", "全天候"]),
    ("高频",     ["高频", "日内", "T+0"]),
    ("期货",     ["期货", "期指", "对冲"]),
]

# 置顶噪声（长期霸屏的系统公告/指南，直接排除）
NOISE_TITLES = [
    "聚宽新手指南",
    "停止对非中国大陆地区",
    "IP 地址服务",
]


def fetch_page(cate: str, page: int) -> list:
    params = {
        "page": page,
        "limit": PAGE_LIMIT,
        "cate": cate,
        "word": "",
        "type": "isNew",
        "tags": "",
        "ajax": "1",
    }
    qs = urllib.parse.urlencode(params)
    url = f"{BASE}/community/post/listV2?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER})
    d = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.loads(resp.read().decode("utf-8", "ignore"))
            break
        except Exception as e:
            if attempt == 2:
                print(f"  [FAIL] cate={cate} page={page}: {e}")
                return []
            time.sleep(2)
    code = str((d or {}).get("code"))
    if code not in ("00000", "0"):
        print(f"  [FAIL] cate={cate} page={page}: code={code} {(d or {}).get('msg')}")
        return []
    data = (d or {}).get("data") or {}
    return data.get("list") or []


def parse_dt(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def clean_snippet(content: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def detect_topics(title: str, desc: str) -> list:
    text = f"{title} {desc}".lower()
    hits = []
    for topic, kws in TOPIC_KEYWORDS:
        if any(kw.lower() in text for kw in kws):
            hits.append(topic)
    return hits[:TOPIC_LIMIT]


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    print(f"[JOINQUANT] 开始抓取，窗口 = 近 {WINDOW_DAYS} 天")

    items = []
    seen = set()
    for cat in CATEGORIES:
        cate, label, pages = cat["cate"], cat["label"], cat["pages"]
        print(f"  [FETCH] cate={cate} ({label}) x{pages} 页")
        for page in range(1, pages + 1):
            raw = fetch_page(cate, page)
            if not raw:
                break
            added_this_page = 0
            for it in raw:
                pid = it.get("postId")
                if not pid or pid in seen:
                    continue
                title = strip_html(it.get("title") or "")
                if not title:
                    continue
                # 置顶噪声过滤
                if any(n in title for n in NOISE_TITLES):
                    continue
                pub = parse_dt(it.get("addTime", ""))
                if pub is None or pub < cutoff:
                    continue
                snippet = clean_snippet(strip_html(it.get("content") or ""))
                topics = detect_topics(title, snippet)
                seen.add(pid)
                added_this_page += 1
                items.append({
                    "id": pid,
                    "title": title,
                    "url": f"{BASE}/view/community/detail/{pid}",
                    "description": snippet,
                    "source": f"聚宽回测: {label}",
                    "site_name": "joinquant.com",
                    "site_id": "joinquant",
                    "category": "量化策略",
                    "topics": topics,
                    "tags": [t.get("name", "") for t in (it.get("tagInfo") or [])],
                    "add_time": it.get("addTime"),
                    "view_count": int(it.get("viewCount") or 0),
                    "like_count": int(it.get("likeCount") or 0),
                    "reply_count": int(it.get("replyCount") or 0),
                    "author": (it.get("user") or {}).get("name") or "",
                    "date_str": pub.strftime("%Y-%m-%d"),
                    "published_at": pub.isoformat(),
                })
            if added_this_page == 0 and page == 1:
                # 首页全是老文，停止翻页
                break
            if len(raw) < PAGE_LIMIT:
                break
        print(f"  [OK] cate={cate} 窗口内累计 {len(items)} 条")

    # 排序：有主题标签的排前，其次按时间倒序
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    items.sort(key=lambda x: 0 if x.get("topics") else 1)  # 稳定排序：主题命中排前

    # 可选：套虎嗅五维评分（CI 有 feedparser 时）
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from update_news import relevance_score
        from huxiu_score import calibrate_scores
        now_ts = now.timestamp()
        for item in items:
            item["relevance"] = relevance_score(item["title"], (item.get("description") or "")[:200])
            item["authority"] = 15
        calibrate_scores(items, now_ts)
        print(f"[JOINQUANT] Scored {len(items)} items (huxiu-calibrated)")
    except Exception as e:
        print(f"[JOINQUANT] huxiu scoring unavailable ({e}), using fallback scoring")
        for item in items:
            text = item["title"] + " " + (item.get("description") or "")
            score = 40
            for kw in ["策略", "回测", "因子", "量化", "年化", "夏普", "选股", "止损", "轮动"]:
                if kw in text:
                    score += 8
                    break
            score = min(90, score + item.get("like_count", 0) // 50 + len(item.get("topics", [])) * 5)
            item["relevance"] = round(score / 100, 2)
            item["authority"] = 15
            item["depth"] = 3
            item["timeliness"] = 20
            item["total_score"] = score

    items = items[:MAX_ITEMS]
    output = {
        "generated_at": now.isoformat(),
        "total_items": len(items),
        "window_days": WINDOW_DAYS,
        "topic_counts": {
            t: sum(1 for it in items if t in it.get("topics", []))
            for t, _ in TOPIC_KEYWORDS
        },
        "items": items,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[JOINQUANT] 已保存 {os.path.normpath(OUTPUT_FILE)}: {len(items)} 条")
    print("  主题分布:", {k: v for k, v in output["topic_counts"].items() if v})

    print("\n[JOINQUANT] 前 10 条:")
    for i, it in enumerate(items[:10], 1):
        topics = "/".join(it.get("topics", [])) or "-"
        print(f"  {i}. [{topics}] {it['title'][:44]}  ({it.get('date_str')})")


if __name__ == "__main__":
    main()
