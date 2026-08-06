#!/usr/bin/env python3
"""arXiv cs.RO 机器人论文抓取器

每30分钟运行一次，抓取arXiv cs.RO类别的最新机器人论文。
输出到 data/arxiv-papers.json，供前端学术专区使用。
"""
import os
import re
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


ARXIV_API = "https://export.arxiv.org/api/query"
CATEGORIES = {
    "cs.RO": "Robotics",
    "cs.AI": "Artificial Intelligence",
    "cs.CV": "Computer Vision",
    "cs.LG": "Machine Learning",
}


def fetch_arxiv_robotics(max_results=20) -> list[dict]:
    """Fetch recent papers from arXiv cs.RO category."""
    params = {
        "search_query": "cat:cs.RO",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    headers = {
        "User-Agent": "AI-News-Radar/1.0 (arXiv fetcher; mailto:radar@example.com)"
    }

    try:
        resp = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        return parse_arxiv_response(resp.text)
    except Exception as e:
        print(f"[ARXIV] Fetch error: {e}")
        return []


def parse_arxiv_response(xml_text: str) -> list[dict]:
    """Parse arXiv API XML response."""
    items = []

    # Extract entries
    entries = re.findall(r'<entry>(.*?)</entry>', xml_text, re.DOTALL)
    for entry_xml in entries:
        item = parse_entry(entry_xml)
        if item:
            items.append(item)

    return items


def parse_entry(entry_xml: str) -> dict | None:
    """Parse a single arXiv entry."""
    def extract_tag(tag: str) -> str | None:
        m = re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', entry_xml, re.DOTALL)
        if m:
            return m.group(1).strip()
        return None

    arxiv_id = extract_tag("id")
    if not arxiv_id:
        return None

    # Skip versioned URLs (keep only abs base)
    abs_match = re.search(r'https?://arxiv\.org/abs/([^v]+?)(?:v\d+)?$', arxiv_id)
    if abs_match:
        arxiv_id_clean = abs_match.group(1)
        url = f"https://arxiv.org/abs/{arxiv_id_clean}"
    else:
        url = arxiv_id

    title = extract_tag("title")
    if not title:
        return None
    # Clean title: remove newlines and extra whitespace
    title = re.sub(r'\s+', ' ', title).strip()

    summary = extract_tag("summary")
    if summary:
        summary = re.sub(r'\s+', ' ', summary).strip()

    # Parse published date
    published = extract_tag("published")
    published_at = None
    if published:
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            published_at = dt.isoformat()
        except Exception:
            pass

    # Extract authors (first 3)
    authors_raw = re.findall(r'<author>\s*<name>(.*?)</name>\s*</author>', entry_xml)
    if len(authors_raw) > 3:
        authors = ", ".join(authors_raw[:3]) + " et al."
    elif authors_raw:
        authors = ", ".join(authors_raw)
    else:
        authors = "Unknown"

    # Extract primary category
    category_match = re.search(r'<category\s+term="([^"]+)"', entry_xml)
    category = category_match.group(1) if category_match else "cs.RO"

    # Extract updated date
    updated = extract_tag("updated")

    return {
        "id": arxiv_id,
        "title": title,
        "url": url,
        "summary": summary or "",
        "authors": authors,
        "category": category,
        "published_at": published_at,
        "updated_at": updated,
    }


def filter_by_time_window(items: list[dict], window_hours: int = 24) -> list[dict]:
    """Filter papers to the time window.

    FIX (2026-08-06): 用滑动窗口 (默认 36h) 替代 19:00 anchor。
    原因：arXiv 每日新论文约在北京时间 02:00 发布（美国东部 14:00 EST）。
    19:00 anchor 早晨跑会错过整整一个发布日的数据，导致页面 0 条。
    滑动 36h 保证覆盖一次完整发布周期（>24h），又不会展示太旧的。
    """
    shanghai = ZoneInfo('Asia/Shanghai')
    now_sh = datetime.now(shanghai)
    now_ts = datetime.now(timezone.utc).timestamp()

    # 滑动窗口：默认 36h（覆盖 arXiv 一次完整发布日 + 缓冲）
    effective_hours = max(window_hours, 36)
    start_dt = now_sh - timedelta(hours=effective_hours)
    start_ts = start_dt.timestamp()

    filtered = []
    for item in items:
        pub = item.get("published_at")
        if not pub:
            filtered.append(item)
            continue
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if start_ts <= dt.timestamp() <= now_ts:
                filtered.append(item)
        except Exception:
            filtered.append(item)
    return filtered


def main(output_dir: str = "data", window_hours: int = 24):
    print(f"[ARXIV] Fetching latest robotics papers...")
    items = fetch_arxiv_robotics(max_results=30)
    print(f"[ARXIV] Fetched {len(items)} papers")

    filtered = filter_by_time_window(items, window_hours=window_hours)
    print(f"[ARXIV] After {window_hours}h window filter: {len(filtered)} papers")

    os.makedirs(output_dir, exist_ok=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_items": len(filtered),
        "items": filtered,
    }
    output_path = os.path.join(output_dir, "arxiv-papers.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[ARXIV] Saved {len(filtered)} papers to {output_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="data")
    p.add_argument("--window-hours", type=int, default=24)
    args = p.parse_args()
    main(args.output_dir, args.window_hours)