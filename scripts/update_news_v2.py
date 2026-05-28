"""
update_news_v2.py — Radar System v2
采集范围：泛机器人、人形机器人、具身智能、物理AI、脑机接口
时间窗口：昨天9点至今（上海时区），增量更新
分类体系：5大类×3子类 = 15分类
"""

import os
import re
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "data", "latest-24h.json")
SEEN_URLS_FILE = os.path.join(SCRIPT_DIR, "data", "seen_urls.json")

# ─────────────────────────────────────────────
# Time Window
# ─────────────────────────────────────────────
SHANGHAI_TZ = timezone(timedelta(hours=8))
now = datetime.now(SHANGHAI_TZ)
yesterday_date = now.date() - timedelta(days=1)
WINDOW_START = datetime(yesterday_date.year, yesterday_date.month, yesterday_date.day, 9, 0, tzinfo=SHANGHAI_TZ)
WINDOW_END = now

# ─────────────────────────────────────────────
# Categories (15)
# ─────────────────────────────────────────────
CATEGORIES = [
    "泛机器人_行业动态", "泛机器人_学术成果", "泛机器人_投融资",
    "人形机器人_行业动态", "人形机器人_学术成果", "人形机器人_投融资",
    "具身智能_行业动态", "具身智能_学术成果", "具身智能_投融资",
    "物理AI_行业动态", "物理AI_学术成果", "物理AI_投融资",
    "脑机接口_行业动态", "脑机接口_学术成果", "脑机接口_投融资",
]

# ─────────────────────────────────────────────
# Exclusion Keywords
# ─────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "机器人ETF", "ETF基金", "股票代码", "沪深", "纳斯达克",
    "roomba", "irobot", "扫地机器人", "扫地机",
]

# ─────────────────────────────────────────────
# Funding Keywords
# ─────────────────────────────────────────────
FUNDING_KEYWORDS = [
    "A轮", "B轮", "C轮", "D轮", "E轮", "Pre-A", "Pre-B",
    "融资", "投资", "募资", "funding", "investment", "invested",
    "raises", "raised", "round", "Series A", "Series B", "Series C",
    "seed round", "天使轮", "战略投资", "股权融资",
]

# ─────────────────────────────────────────────
# arXiv categories for each domain
# ─────────────────────────────────────────────
ARXIV_CATEGORIES = {
    "robot":       "cs.RO",
    "robotics":    "cs.RO",
    "humanoid":    "cs.RO",
    "embodied":    "cs.AI",
    "brain":       "cs.NE",
    "neural":      "cs.NE",
}

# ─────────────────────────────────────────────
# Data Source Config
# ─────────────────────────────────────────────
GN_FEEDS = [
    # (search_query, source_label)
    # Use exact-phrase "term" + negative -term to reduce noise
    ('"humanoid robot"',              "GN: humanoid robot"),
    ('"embodied intelligence"',        "GN: embodied intelligence"),
    ('"physical AI" -limitations',     "GN: physical AI"),
    ('"brain computer interface"',     "GN: BCI"),
    ('robot industry OR robotics news OR "service robot" OR "industrial robot"', "GN: robot"),
]

RSSHUB_BAIDU_KEYWORDS = [
    "人形机器人", "具身智能", "物理AI", "脑机接口", "机器人",
]
RSSHUB_GOOGLE_CN_KEYWORDS = [
    "humanoid robot", "embodied intelligence",
]
RSSHUB_WECHAT_KEYWORDS = [
    "人形机器人", "具身智能", "物理AI", "脑机接口", "机器人",
]

# ─────────────────────────────────────────────
# RSSHub host (change for self-hosted)
# ─────────────────────────────────────────────
RSSHUB_HOST = os.environ.get("RSSHUB_HOST", "http://localhost:1200")

# ─────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; RadarBot/2.0; +http://example.com/bot)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
})

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def md5_id(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]

def parse_iso_time(date_str: str, fallback: datetime = None) -> datetime:
    """Parse various date formats to datetime."""
    if not date_str:
        return fallback or datetime.now(SHANGHAI_TZ)
    date_str = date_str.strip()
    # Try ISO format
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=SHANGHAI_TZ)
            return dt
        except ValueError:
            pass
    # Try fromisoformat
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SHANGHAI_TZ)
        return dt
    except Exception:
        pass
    return fallback or datetime.now(SHANGHAI_TZ)

def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch URL; returns None on failure so caller can skip gracefully."""
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  [WARN] fetch failed: {url} → {e}")
        return None

def parse_rss_items(xml_text: str, source_label: str) -> list[dict]:
    """Parse RSS XML and return list of items."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"  [WARN] XML parse error ({source_label}): {e}")
        return items

    # RSS 2.0
    for channel in root.findall("channel"):
        for item in channel.findall("item"):
            title = _get_text(item, "title")
            link  = _get_text(item, "link")
            desc  = _get_text(item, "description") or ""
            pub   = _get_text(item, "pubDate") or _get_text(item, "dc:date") or ""
            if not link:
                link = _get_text(item, "guid") or ""
            if title and link:
                items.append({
                    "title": clean_text(title),
                    "url":   link.strip(),
                    "desc":  clean_text(desc),
                    "pub":   pub,
                    "source": source_label,
                })

    # Atom
    for entry in root.findall("entry"):
        title  = _get_text(entry, "title")
        link_el = entry.find("link")
        link   = link_el.get("href") if link_el is not None else ""
        if not link:
            link = _get_text(entry, "id") or ""
        desc   = _get_text(entry, "summary") or _get_text(entry, "content") or ""
        pub    = _get_text(entry, "published") or _get_text(entry, "updated") or ""
        if title and link:
            items.append({
                "title": clean_text(title),
                "url":   link.strip(),
                "desc":  clean_text(desc),
                "pub":   pub,
                "source": source_label,
            })

    # RSS 1.0 / Atom fallback — search all <item> tags
    if not items:
        for item in root.findall(".//item"):
            title = _get_text(item, "title")
            link  = _get_text(item, "link") or _get_text(item, "guid") or ""
            desc  = _get_text(item, "description") or ""
            pub   = _get_text(item, "pubDate") or _get_text(item, "dc:date") or ""
            if title and link:
                items.append({
                    "title": clean_text(title),
                    "url":   link.strip(),
                    "desc":  clean_text(desc),
                    "pub":   pub,
                    "source": source_label,
                })
    return items

def _get_text(elem, tag: str) -> str:
    found = elem.find(tag)
    if found is not None and found.text:
        return found.text
    # also try namespace variants
    for child in elem:
        if child.tag.endswith(f":{tag}") or child.tag == tag:
            return child.text or ""
    return ""

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]  # truncate

def is_excluded(title: str, url: str = "", desc: str = "") -> bool:
    text = f"{title} {url} {desc}".lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in text:
            return True
    return False

def route_to_category(title: str, url: str = "", desc: str = "", source: str = "", is_arxiv: bool = False) -> str:
    """
    Route an item to one of 15 categories.
    Priority:
    1. arXiv papers → "学术成果"
    2. funding keywords → "投融资"
    3. domain-specific keywords → domain-specific
    4. Fallback → "行业动态"
    """
    combined = f"{title} {url} {desc}".lower()
    title_lower = title.lower()

    # 1. arXiv → 学术成果 (infer domain from title)
    if is_arxiv:
        if any(k in combined for k in ["humanoid", "bipedal", "两足", "人形"]):
            return "人形机器人_学术成果"
        if any(k in combined for k in ["embodied", "具身", "physical ai"]):
            return "具身智能_学术成果"
        if any(k in combined for k in ["physical ai", "physics", "物理"]):
            return "物理AI_学术成果"
        if any(k in combined for k in ["brain", "neural", "bci", "脑机", "neuro"]):
            return "脑机接口_学术成果"
        return "泛机器人_学术成果"

    # 2. Funding keywords
    has_funding = any(kw in combined for kw in FUNDING_KEYWORDS)
    
    # 3. Domain-specific routing
    # 人形机器人
    if "humanoid" in combined or "人形" in title or "人形机器人" in combined:
        return "人形机器人_投融资" if has_funding else "人形机器人_行业动态"
    
    # 具身智能
    if "embodied intelligence" in combined or "具身智能" in title or "具身智能" in combined:
        return "具身智能_投融资" if has_funding else "具身智能_行业动态"

    # 物理AI（必须 title 包含 physical AI，防止误匹配 physical limitations）
    if "physical ai" in title_lower:
        return "物理AI_投融资" if has_funding else "物理AI_行业动态"

    # 脑机接口
    if any(k in combined for k in ["brain computer interface", "bci", "脑机接口", "brain-machine", "neural interface"]):
        return "脑机接口_投融资" if has_funding else "脑机接口_行业动态"

    # 人形机器人
    if "humanoid" in title_lower or "人形机器人" in title or "人形" in title:
        return "人形机器人_投融资" if has_funding else "人形机器人_行业动态"

    # 泛机器人（宽线，需 title 包含 robot 语义，防止泛匹配）
    if any(k in title_lower for k in ["robot", "robots", "robotics", "robotic", "drone", "autonomous"]):
        return "泛机器人_投融资" if has_funding else "泛机器人_行业动态"

    # Fallback → 跳过，不入库
    return None

def within_window(pub_str: str, window_start: datetime = None, window_end: datetime = None) -> bool:
    """Check if published time is within window.
    
    Args:
        pub_str: ISO date string from the item
        window_start: override start (default WINDOW_START)
        window_end: override end (default WINDOW_END)
    """
    if not pub_str:
        return True  # include if unknown
    dt = parse_iso_time(pub_str)
    ws = window_start if window_start is not None else WINDOW_START
    we = window_end if window_end is not None else WINDOW_END
    return ws <= dt <= we

def arxiv_window(pub_str: str) -> bool:
    """arXiv has its own window: last 7 days (arXiv papers are dated by submission, not publication)."""
    if not pub_str:
        return True
    dt = parse_iso_time(pub_str)
    ARXIV_WINDOW_START = datetime.now(SHANGHAI_TZ) - timedelta(days=7)
    return ARXIV_WINDOW_START <= dt

def score_by_relevance(title: str, keywords: list[str]) -> float:
    """Score title relevance by keyword hits."""
    title_lower = title.lower()
    score = 0.0
    for kw in keywords:
        if kw.lower() in title_lower:
            score += 1.0
    return min(score, 5.0)

# ─────────────────────────────────────────────
# arXiv Fetcher
# ─────────────────────────────────────────────
ARXIV_KEYWORD_POOLS = {
    "humanoid robot":    ["humanoid robot", "humanoid", "bipedal robot", "android"],
    "embodied intelligence": ["embodied intelligence", "embodied AI", "具身智能", "embodied"],
    "physical AI":       ["physical AI", "physics-based AI", "physics AI"],
    "brain computer interface": ["brain computer interface", "BCI", "neural interface", "brain-machine"],
    "robot robotics":    ["robot", "robotics", "autonomous robot", "robotic system"],
}

def fetch_arxiv(category_key: str, pool_keywords: list[str]) -> list[dict]:
    """
    Fetch recent arXiv papers for a given category.
    arXiv RSS: https://export.arxiv.org/rss/{cat}  (e.g. cs.RO, cs.AI, cs.NE)
    """
    arxiv_cat = ARXIV_CATEGORIES.get(category_key.split()[0].lower(), "cs.RO")
    url = f"https://export.arxiv.org/rss/{arxiv_cat}"
    xml_text = fetch_url(url, timeout=20)
    if not xml_text:
        return []

    items = parse_rss_items(xml_text, f"arXiv: {category_key}")
    scored = []
    for it in items:
        score = score_by_relevance(it["title"], pool_keywords)
        if score > 0:
            scored.append({**it, "score": score})
    # Sort by score desc, keep top 20
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:20]

# ─────────────────────────────────────────────
# Main Gather Loop
# ─────────────────────────────────────────────
def gather_all() -> list[dict]:
    all_items = []
    seen_urls = load_seen_urls()

    # ── 1. Google News RSS Feeds ──
    print("[1/4] Fetching Google News RSS feeds...")
    for keyword, label in GN_FEEDS:
        # Google News RSS: sortBy=s → Sort by Relevance (default latest can flood with old items)
        url = (f"https://news.google.com/rss/search?q={requests.utils.quote(keyword)}"
               f"&hl=en-US&gl=US&ceid=US:en&sortBy=s")
        print(f"  → {label}")
        xml_text = fetch_url(url)
        items = parse_rss_items(xml_text, label)
        for it in items:
            if is_excluded(it["title"], it["url"], it["desc"]):
                continue
            if not within_window(it["pub"]):
                continue
            if it["url"] in seen_urls:
                continue
            cat = route_to_category(it["title"], it["url"], it["desc"], it["source"])
            if cat is None:
                continue
            all_items.append(_make_item(it, cat))
        print(f"    got {len(items)} items")

    # ── 2. RSSHub Baidu News ──
    print("[2/4] Fetching RSSHub Baidu News...")
    if not RSSHUB_HOST:
        print("  [SKIP] RSSHUB_HOST not set")
    else:
        for kw in RSSHUB_BAIDU_KEYWORDS:
            url = f"{RSSHUB_HOST}/baidu/search/{requests.utils.quote(kw)}"
            label = f"百度: {kw}"
            print(f"  → {label}")
            xml_text = fetch_url(url)
            if xml_text is None:
                print(f"    [SKIP] fetch failed")
                continue
            items = parse_rss_items(xml_text, label)
            count = 0
            for it in items:
                if is_excluded(it["title"], it["url"], it["desc"]):
                    continue
                if not within_window(it["pub"]):
                    continue
                if it["url"] in seen_urls:
                    continue
                cat = route_to_category(it["title"], it["url"], it["desc"], it["source"])
                if cat is None:
                    continue
                all_items.append(_make_item(it, cat))
                count += 1
            print(f"    got {count} new items")

    # ── 3. RSSHub WeChat Search ──
    print("[3/4] Fetching RSSHub WeChat Search...")
    if not RSSHUB_HOST:
        print("  [SKIP] RSSHUB_HOST not set")
    else:
        for kw in RSSHUB_WECHAT_KEYWORDS:
            url = f"{RSSHUB_HOST}/wechat/sogou/{requests.utils.quote(kw)}"
            label = f"微信: {kw}"
            print(f"  → {label}")
            xml_text = fetch_url(url)
            if xml_text is None:
                print(f"    [SKIP] fetch failed")
                continue
            items = parse_rss_items(xml_text, label)
            count = 0
            for it in items:
                if is_excluded(it["title"], it["url"], it["desc"]):
                    continue
                if not within_window(it["pub"]):
                    continue
                if it["url"] in seen_urls:
                    continue
                cat = route_to_category(it["title"], it["url"], it["desc"], it["source"])
                if cat is None:
                    continue
                all_items.append(_make_item(it, cat))
                count += 1
            print(f"    got {count} new items")

    # ── 4. arXiv ──
    print("[4/4] Fetching arXiv papers...")
    for cat_key, pool_kws in ARXIV_KEYWORD_POOLS.items():
        print(f"  → arXiv: {cat_key}")
        papers = fetch_arxiv(cat_key, pool_kws)
        count = 0
        for it in papers:
            if is_excluded(it["title"], it["url"], it["desc"]):
                continue
            # arXiv: use 7-day window (arXiv papers are dated by submission)
            if not arxiv_window(it["pub"]):
                continue
            if it["url"] in seen_urls:
                continue
            cat = route_to_category(it["title"], it["url"], it["desc"], it["source"], is_arxiv=True)
            if cat is None:
                continue
            all_items.append(_make_item(it, cat))
            count += 1
        print(f"    got {count} new papers")

    # Deduplicate by URL within this run
    seen_this_run = set()
    deduped = []
    for item in all_items:
        if item["url"] not in seen_this_run:
            seen_this_run.add(item["url"])
            deduped.append(item)

    # Sort by published_at descending
    def sort_key(item):
        dt = parse_iso_time(item["published_at"])
        return dt
    deduped.sort(key=sort_key, reverse=True)

    return deduped

def _make_item(it: dict, category: str) -> dict:
    pub_dt = parse_iso_time(it["pub"])
    summary = it.get("desc", "")[:300]
    return {
        "id": md5_id(it["url"]),
        "title": it["title"],
        "url": it["url"],
        "source": it["source"],
        "published_at": pub_dt.isoformat(),
        "score": it.get("score", 0.0),
        "category": category,
        "summary": summary,
    }

# ─────────────────────────────────────────────
# Seen URLs persistence
# ─────────────────────────────────────────────
def load_seen_urls() -> set[str]:
    if not os.path.exists(SEEN_URLS_FILE):
        return set()
    try:
        with open(SEEN_URLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("urls", []))
    except Exception as e:
        print(f"[WARN] Could not load seen_urls: {e}")
        return set()

def save_seen_urls(urls: set[str]):
    try:
        existing = set()
        if os.path.exists(SEEN_URLS_FILE):
            try:
                with open(SEEN_URLS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing = set(data.get("urls", []))
            except Exception:
                pass
        merged = existing | urls
        # Keep max 50000 URLs
        if len(merged) > 50000:
            merged = set(list(merged)[-50000:])
        with open(SEEN_URLS_FILE, "w", encoding="utf-8") as f:
            json.dump({"urls": list(merged)}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Could not save seen_urls: {e}")

# ─────────────────────────────────────────────
# Build output JSON
# ─────────────────────────────────────────────
def build_output(items: list[dict]) -> dict:
    categories = {cat: [] for cat in CATEGORIES}
    for item in items:
        cat = item["category"]
        if cat in categories:
            categories[cat].append(item)
        else:
            categories["泛机器人_行业动态"].append(item)

    return {
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat(),
        "window_start": WINDOW_START.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "total_items": len(items),
        "categories": categories,
    }

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Radar System v2 — News Update")
    print(f"Window: {WINDOW_START.isoformat()} → {WINDOW_END.isoformat()}")
    print("=" * 60)

    # Gather all items
    items = gather_all()
    print(f"\nTotal new items gathered: {len(items)}")

    # Build output
    output = build_output(items)

    # Save
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Output saved to: {OUTPUT_FILE}")

    # Update seen URLs
    urls = {item["url"] for item in items}
    save_seen_urls(urls)
    print(f"Updated seen URLs (+{len(urls)} new)")

    # Summary
    print("\n--- Category Summary ---")
    for cat, cat_items in output["categories"].items():
        if cat_items:
            print(f"  {cat}: {len(cat_items)}")

    print("\nDone.")

if __name__ == "__main__":
    main()
