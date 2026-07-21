#!/usr/bin/env python3
"""
微信公众号文章采集器 v2 — 集成 wechat-article-claw

功能：
  1. 通过 Exa MCP 搜索微信公众号文章（site:mp.weixin.qq.com）
  2. 使用 wechat-fetch.py 抓取文章正文，过滤无关内容
  3. 合并用户手动提供的文章列表（wechat-manual.json）
  4. 输出标准化格式，接入 update_news.py pipeline

用法：
  python wechat-collector-v2.py --manual                    # 只加载手动文章
  python wechat-collector-v2.py --search "具身智能"          # 搜索 + 手动
  python wechat-collector-v2.py --all                       # 全量搜索 + 手动
  python wechat-collector-v2.py --output wechat-out.json    # 输出到文件
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

DEFAULT_KEYWORDS = [
    "具身智能", "机器人", "人形机器人", "脑机接口",
    "Physical AI", "embodied AI", "humanoid robot", "AI 机器人",
]

RELEVANCE_KEYWORDS = [
    "机器人", "人形", "具身", "AI", "人工智能", "智能", "机械",
    "brain-computer", "BCI", "脑机", "肢体", "操控", "运动",
    "humanoid", "embodied", "physical AI", "robotics", "robot",
    "Tesla", "Optimus", "Figure", "Unitree", "宇树", "智元",
    "Boston Dynamics", "波士顿动力", "Atlas", "G1", "H1",
    "小米", "CyberDog", "铁蛋", "Iron",
]


def sha1_short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_wechat_time(published_str: str) -> str:
    if not published_str:
        return now_iso()
    try:
        if " " in published_str:
            dt = datetime.strptime(published_str.strip(), "%Y-%m-%d %H:%M")
        else:
            dt = datetime.strptime(published_str.strip(), "%Y-%m-%d")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return now_iso()


def search_wechat_via_exa(keyword: str, max_results: int = 20) -> list[dict]:
    """通过 Exa MCP 搜索微信公众号文章."""
    results = []
    try:
        result = subprocess.run(
            ["python", "-c", f"""
import requests, json, subprocess, sys
EXA_MCP_URL = "https://mcp.exa.ai/mcp"
def exa_call(tool_name, arguments, timeout=30):
    payload = {{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {{"name": tool_name, "arguments": arguments}}}}
    headers = {{"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}}
    r = requests.post(EXA_MCP_URL, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace").strip()
    for line in text.split("\\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            if "error" in data: return {{"error": data["error"]}}
            return data.get("result", {{}})
    return {{"error": "no data in response"}}
result = exa_call("web_search_exa", {{"query": "site:mp.weixin.qq.com {keyword}", "numResults": {max_results}}})
if "error" in result:
    print(f"EXA_ERROR: {{result['error']}}"); sys.exit(1)
for r in result.get("results", []):
    print(json.dumps({{"title": r.get("title", ""), "url": r.get("url", ""),
        "publishedAt": r.get("publishedDate", ""), "snippet": r.get("text", "")[:200]}}, ensure_ascii=False))
"""],
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("EXA_ERROR:"): continue
                try:
                    article = json.loads(line)
                    if article.get("url") and article.get("title"):
                        results.append(article)
                except json.JSONDecodeError: continue
    except Exception as e:
        print(f"[WECHAT] Exa MCP 搜索失败 {keyword}: {e}")
    return results


def fetch_and_filter_wechat_article(url: str) -> Optional[dict]:
    """使用 wechat-fetch.py 抓取正文并过滤无关内容."""
    try:
        wechat_fetch_paths = [
            Path.home() / ".hermes" / "skills" / "wechat-article-claw" / "wechat-fetch.py",
            Path.home() / ".openclaw" / "skills" / "wechat-article-claw" / "wechat-fetch.py",
            Path.home() / "AppData" / "Local" / "hermes" / "skills" / "wechat-article-claw" / "wechat-fetch.py",
        ]
        fetch_script = None
        for p in wechat_fetch_paths:
            if p.exists():
                fetch_script = str(p)
                break
        if not fetch_script:
            return None
        result = subprocess.run(
            ["python", fetch_script, url],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            content = result.stdout.strip()
            if len(content) > 200:
                content_lower = content.lower()
                relevance_score = sum(1 for kw in RELEVANCE_KEYWORDS if kw.lower() in content_lower)
                if relevance_score >= 2:
                    return {"content": content[:2000], "relevance_score": relevance_score, "success": True}
                else:
                    print(f"[WECHAT] 文章不相关 (relevance={relevance_score}): {url}")
                    return None
    except Exception as e:
        print(f"[WECHAT] 抓取失败 {url}: {e}")
    return None


def load_manual_articles() -> list[dict]:
    """加载用户手动添加的微信公众号文章，支持多种格式."""
    manual_paths = [
        Path.home() / ".hermes" / "wechat-manual.json",
        Path.home() / "AppData" / "Local" / "hermes" / "wechat-manual.json",
        Path.cwd() / "wechat-manual.json",
    ]
    for p in manual_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 支持两种格式: [{"url": ...}] 或 {"articles": [{"url": ...}]}
                if isinstance(data, list):
                    articles = data
                elif isinstance(data, dict) and "articles" in data:
                    articles = data["articles"]
                else:
                    print(f"[WECHAT] 未知格式 {p}")
                    return []
                print(f"[WECHAT] 加载手动文章: {len(articles)} 条 ({p})")
                return articles
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WECHAT] 加载手动文章失败 {p}: {e}")
                return []
    print("[WECHAT] 未找到手动文章文件")
    return []


def collect_wechat_articles(
    keywords: list[str] = None,
    hours: int = 24,
    max_per_keyword: int = 20,
    include_manual: bool = True,
    filter_by_content: bool = True,
) -> list[dict]:
    """采集微信公众号文章."""
    if keywords is None:
        keywords = DEFAULT_KEYWORDS
    all_articles = {}
    print(f"[WECHAT] 开始搜索 {len(keywords)} 个关键词...")
    for kw in keywords:
        print(f"  搜索: {kw}")
        search_results = search_wechat_via_exa(kw, max_results=max_per_keyword)
        print(f"    找到 {len(search_results)} 篇")
        for sr in search_results:
            url = sr.get("url", "")
            if not url or url in all_articles:
                continue
            filtered = None
            if filter_by_content:
                filtered = fetch_and_filter_wechat_article(url)
            all_articles[url] = {
                "title": sr.get("title", ""),
                "url": url,
                "published_at": normalize_wechat_time(sr.get("publishedAt", "")),
                "source": "微信公众号",
                "description": filtered["content"] if filtered else (sr.get("snippet", "") or ""),
                "relevance_score": filtered["relevance_score"] if filtered else 0,
                "first_seen_at": now_iso(),
            }
    print(f"[WECHAT] 搜索得到 {len(all_articles)} 篇去重文章")
    if include_manual:
        manual = load_manual_articles()
        for m in manual:
            url = m.get("url", "")
            if not url or url in all_articles:
                continue
            all_articles[url] = {
                "title": m.get("title", ""),
                "url": url,
                "published_at": normalize_wechat_time(m.get("published_at", "")),
                "source": m.get("source", "微信公众号"),
                "description": m.get("description", m.get("notes", "")),
                "relevance_score": 10,
                "first_seen_at": now_iso(),
            }
    results = []
    for url, article in all_articles.items():
        results.append({
            "id": sha1_short(url),
            "title": article.get("title", ""),
            "title_zh": "",
            "url": url,
            "published_at": article.get("published_at", now_iso()),
            "site_name": "微信公众号",
            "site_id": "wechat",
            "source": article.get("source", "微信公众号"),
            "description": article.get("description", ""),
            "ai_score": 0, "relevance": 0, "authority": 0,
            "depth": 0, "timeliness": 0, "writing_value": 0, "total_score": 0,
            "ai_label": "wechat",
            "first_seen_at": article.get("first_seen_at", now_iso()),
        })
    results.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    print(f"[WECHAT] 最终输出 {len(results)} 篇标准化文章")
    return results


def main():
    parser = argparse.ArgumentParser(description="微信公众号文章采集器 v2")
    parser.add_argument("--search", nargs="+", help="搜索关键词")
    parser.add_argument("--hours", type=int, default=24, help="搜索时间范围（小时）")
    parser.add_argument("--max-per-keyword", type=int, default=20, help="每个关键词最大结果数")
    parser.add_argument("--manual", action="store_true", help="同时加载手动添加的文章")
    parser.add_argument("--no-filter", action="store_true", help="跳过正文抓取和内容过滤")
    parser.add_argument("--output", "-o", help="输出文件路径（JSON）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不输出")
    args = parser.parse_args()
    keywords = args.search if args.search else DEFAULT_KEYWORDS
    articles = collect_wechat_articles(
        keywords=keywords, hours=args.hours, max_per_keyword=args.max_per_keyword,
        include_manual=args.manual, filter_by_content=not args.no_filter,
    )
    if args.dry_run:
        print(f"\n[DRY RUN] 预览 {len(articles)} 篇文章:")
        for a in articles[:5]:
            print(f"  - {a['title']} ({a['url'][:60]}...)")
        if len(articles) > 5:
            print(f"  ... 还有 {len(articles) - 5} 篇")
        return
    if args.output:
        output = {"generated_at": now_iso(), "total": len(articles), "articles": articles}
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 已保存到 {args.output}")
    else:
        output = {"generated_at": now_iso(), "total": len(articles), "articles": articles}
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
