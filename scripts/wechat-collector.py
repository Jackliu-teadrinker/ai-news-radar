#!/usr/bin/env python3
"""
微信公众号文章采集器 — AI News Radar 扩展

功能：
  1. 搜索当日微信公众号文章（通过 Exa MCP site:mp.weixin.qq.com）
  2. 抓取指定公众号文章正文（wechat-fetch.py）
  3. 合并用户手动提供的文章列表（wechat-manual.json）
  4. 输出标准化格式，接入 update_news.py pipeline

数据来源：
  - Exa MCP 搜索：site:mp.weixin.qq.com 关键词检索
  - wechat-fetch.py：微信手机 UA 绕过验证码抓取正文
  - wechat-manual.json：用户手动添加的文章

输出格式（与 update_news.py 统一）：
  {
    "id": "sha1(url)[:16]",
    "title": "文章标题",
    "title_zh": "中文翻译（如有）",
    "url": "原文链接",
    "published_at": "ISO 时间",
    "site_name": "微信公众号",
    "site_id": "wechat",
    "source": "公众号名称",
    "description": "摘要/正文前300字",
    "ai_score": 0,        # 由 ai_relevance.py 后续评分
    "relevance": 0,
    "authority": 0,
    "depth": 0,
    "timeliness": 0,
    "writing_value": 0,
    "total_score": 0,
    "ai_label": "wechat",
    "first_seen_at": "ISO 时间"
  }

用法：
  python wechat-collector.py --search "具身智能 机器人" --hours 24
  python wechat-collector.py --manual
  python wechat-collector.py --search "具身智能" --hours 24 --manual
  python wechat-collector.py --all   # 搜索 + 手动
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

# 微信公众号搜索关键词模板
DEFAULT_KEYWORDS = [
    "具身智能",
    "机器人",
    "人形机器人",
    "脑机接口",
    "Physical AI",
    "embodied AI",
    "humanoid robot",
    "AI 机器人",
]

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────


def sha1_short(text: str) -> str:
    """生成短 SHA1 hash."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    """当前 UTC ISO 时间."""
    return datetime.now(timezone.utc).isoformat()


def hours_ago_iso(hours: int) -> str:
    """返回 hours 前的 ISO 时间."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.isoformat()


def normalize_wechat_time(published_str: str) -> str:
    """标准化微信文章时间."""
    if not published_str:
        return now_iso()
    # 微信文章时间格式：2026-07-15 10:30 或 2026-07-15
    try:
        if " " in published_str:
            dt = datetime.strptime(published_str.strip(), "%Y-%m-%d %H:%M")
        else:
            dt = datetime.strptime(published_str.strip(), "%Y-%m-%d")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return now_iso()


# ─────────────────────────────────────────────
# Exa MCP 搜索（微信公众号文章）
# ─────────────────────────────────────────────


def search_wechat_via_exa(keyword: str, hours: int = 24, max_results: int = 20) -> list[dict]:
    """
    通过 Exa MCP 搜索微信公众号文章。
    
    返回标准化的文章列表。
    """
    results = []
    
    try:
        # 尝试通过 Exa MCP 搜索
        result = subprocess.run(
            ["python", "-c", f"""
import requests, json, subprocess, sys

EXA_MCP_URL = "https://mcp.exa.ai/mcp"

def exa_call(tool_name, arguments, timeout=30):
    payload = {{
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {{"name": tool_name, "arguments": arguments}}
    }}
    headers = {{
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }}
    r = requests.post(EXA_MCP_URL, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace").strip()
    for line in text.split("\\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            if "error" in data:
                return {{"error": data["error"]}}
            return data.get("result", {{}})
    return {{"error": "no data in response"}}

# Search for wechat articles
result = exa_call("web_search_exa", {{
    "query": "site:mp.weixin.qq.com {keyword}",
    "numResults": {max_results},
    "type": "publishDate",
    "publishDate": {{
        "recentHours": {hours}
    }}
}})

if "error" in result:
    print(f"EXA_ERROR: {{result['error']}}")
    sys.exit(1)

# Parse results
results = result.get("results", [])
for r in results:
    print(json.dumps({{
        "title": r.get("title", ""),
        "url": r.get("url", ""),
        "publishedAt": r.get("publishedDate", ""),
        "snippet": r.get("text", "")[:200],
    }}, ensure_ascii=False))
"""],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace"
        )
        
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("EXA_ERROR:"):
                    continue
                try:
                    article = json.loads(line)
                    if article.get("url") and article.get("title"):
                        results.append(article)
                except json.JSONDecodeError:
                    continue
                    
    except FileNotFoundError:
        print(f"[WECHAT] Exa MCP 不可用，跳过搜索: {keyword}")
    except subprocess.TimeoutExpired:
        print(f"[WECHAT] Exa MCP 搜索超时: {keyword}")
    except Exception as e:
        print(f"[WECHAT] Exa MCP 搜索失败 {keyword}: {e}")
    
    return results


# ─────────────────────────────────────────────
# wechat-fetch.py 抓取正文
# ─────────────────────────────────────────────


def fetch_wechat_article(url: str) -> Optional[dict]:
    """
    使用 wechat-fetch.py 抓取微信公众号文章正文。
    
    返回包含标题、摘要、正文等信息的字典。
    """
    try:
        # 尝试找到 wechat-fetch.py
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
            print(f"[WECHAT] wechat-fetch.py 未找到，跳过正文抓取: {url}")
            return None
        
        result = subprocess.run(
            ["python", fetch_script, url],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace"
        )
        
        if result.returncode == 0 and result.stdout.strip():
            content = result.stdout.strip()
            # 如果内容很短，可能是错误信息
            if len(content) > 50:
                return {
                    "content": content[:2000],  # 截断到2000字
                    "success": True,
                }
        
        return None
        
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"[WECHAT] 抓取失败 {url}: {e}")
        return None


# ─────────────────────────────────────────────
# 手动添加的文章
# ─────────────────────────────────────────────


def load_manual_articles() -> list[dict]:
    """
    加载用户手动添加的微信公众号文章。
    
    文件格式 (wechat-manual.json):
    [
      {{
        "title": "文章标题",
        "url": "https://mp.weixin.qq.com/s/xxx",
        "source": "公众号名称",
        "published_at": "2026-07-15 10:30",  // 可选
        "notes": "备注"  // 可选
      }}
    ]
    """
    manual_paths = [
        Path.home() / ".hermes" / "wechat-manual.json",
        Path.home() / "AppData" / "Local" / "hermes" / "wechat-manual.json",
        Path.cwd() / "wechat-manual.json",
    ]
    
    for p in manual_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    articles = json.load(f)
                print(f"[WECHAT] 加载手动文章: {len(articles)} 条 ({p})")
                return articles
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WECHAT] 加载手动文章失败 {p}: {e}")
                return []
    
    print("[WECHAT] 未找到手动文章文件")
    return []


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────


def collect_wechat_articles(
    keywords: list[str] = None,
    hours: int = 24,
    max_per_keyword: int = 20,
    include_manual: bool = True,
) -> list[dict]:
    """
    采集微信公众号文章。
    
    流程：
    1. 通过 Exa MCP 搜索各关键词的公众号文章
    2. 抓取正文（可选，耗时较长）
    3. 合并手动添加的文章
    4. 去重
    5. 输出标准化格式
    
    返回标准化文章列表。
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS
    
    all_articles = {}  # url -> article
    
    # Step 1: Exa MCP 搜索
    print(f"[WECHAT] 开始搜索 {len(keywords)} 个关键词...")
    for kw in keywords:
        print(f"  搜索: {kw}")
        search_results = search_wechat_via_exa(kw, hours=hours, max_results=max_per_keyword)
        for sr in search_results:
            url = sr.get("url", "")
            if not url:
                continue
            if url in all_articles:
                continue
            
            # 尝试抓取正文
            content = None
            if sr.get("snippet"):
                content = sr["snippet"]
            
            all_articles[url] = {
                "title": sr.get("title", ""),
                "url": url,
                "published_at": normalize_wechat_time(sr.get("publishedAt", "")),
                "source": "微信公众号",
                "description": content or "",
                "first_seen_at": now_iso(),
            }
    
    print(f"[WECHAT] 搜索得到 {len(all_articles)} 篇去重文章")
    
    # Step 2: 手动添加
    if include_manual:
        manual = load_manual_articles()
        for m in manual:
            url = m.get("url", "")
            if not url:
                continue
            if url in all_articles:
                continue
            
            all_articles[url] = {
                "title": m.get("title", ""),
                "url": url,
                "published_at": normalize_wechat_time(m.get("published_at", "")),
                "source": m.get("source", "微信公众号"),
                "description": m.get("description", m.get("notes", "")),
                "first_seen_at": now_iso(),
            }
    
    # Step 3: 转换为标准格式
    results = []
    for url, article in all_articles.items():
        results.append({
            "id": sha1_short(url),
            "title": article.get("title", ""),
            "title_zh": "",  # 微信文章通常是中文，不需要翻译
            "url": url,
            "published_at": article.get("published_at", now_iso()),
            "site_name": "微信公众号",
            "site_id": "wechat",
            "source": article.get("source", "微信公众号"),
            "description": article.get("description", ""),
            "ai_score": 0,  # 由 ai_relevance.py 后续评分
            "relevance": 0,
            "authority": 0,
            "depth": 0,
            "timeliness": 0,
            "writing_value": 0,
            "total_score": 0,
            "ai_label": "wechat",
            "first_seen_at": article.get("first_seen_at", now_iso()),
        })
    
    # 按发布时间排序
    results.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    
    print(f"[WECHAT] 最终输出 {len(results)} 篇标准化文章")
    return results


def main():
    parser = argparse.ArgumentParser(description="微信公众号文章采集器")
    parser.add_argument("--search", nargs="+", help="搜索关键词")
    parser.add_argument("--hours", type=int, default=24, help="搜索时间范围（小时）")
    parser.add_argument("--max-per-keyword", type=int, default=20, help="每个关键词最大结果数")
    parser.add_argument("--manual", action="store_true", help="同时加载手动添加的文章")
    parser.add_argument("--output", "-o", help="输出文件路径（JSON）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不输出")
    args = parser.parse_args()
    
    keywords = args.search if args.search else DEFAULT_KEYWORDS
    articles = collect_wechat_articles(
        keywords=keywords,
        hours=args.hours,
        max_per_keyword=args.max_per_keyword,
        include_manual=args.manual,
    )
    
    if args.dry_run:
        print(f"\n[DRY RUN] 预览 {len(articles)} 篇文章:")
        for a in articles[:5]:
            print(f"  - {a['title']} ({a['url'][:60]}...)")
        if len(articles) > 5:
            print(f"  ... 还有 {len(articles) - 5} 篇")
        return
    
    if args.output:
        output = {
            "generated_at": now_iso(),
            "total": len(articles),
            "articles": articles,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 已保存到 {args.output}")
    else:
        # 输出到 stdout
        output = {
            "generated_at": now_iso(),
            "total": len(articles),
            "articles": articles,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
